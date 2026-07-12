# Unattended CLI pipeline

> 一份从命令行直接跑通 "RGB + prompt → `final/asset.usd`" 的笔记，
> 也顺带把当前 Mining Asset Pipeline 的两条端到端路径（CLI / Gradio UI）
> 完整画清楚，作为后续接入 Skill / Claude API / CI 的事实底稿。
>
> 创建时间：2026-07-12
> 适用代码：`src/mining_asset_pipeline/agent/`、`scripts/run_pipeline.py`、
> `scripts/launch_asset_agent.py`

---

## 1. 这是什么

`sripts/run_pipeline.py` 是**完全无人值守**的 CLI 入口。它把 Gradio UI
里需要人工点"批准视觉资产"那一步**省略掉**，直接从命令行接收 image +
prompt，跑完输出 `outputs/<asset_id>/final/asset.usd`。

适合：
- 把 pipeline 当成"图像到 USD"的转换器调用
- 批量处理多张矿业图（dataset 准备）
- 在 CI 里跑（退出码即状态：`0` / `2` / `1`）
- 让别的 Agent（Claude Code Skill / Claude API）调用

不适合：
- 需要人工审查视觉资产再决定是否进入物理审查（用 Gradio UI）

---

## 2. 当前端到端工作流（两条路径）

两条路径都汇聚到**同一份** `AssetWorkflow` 业务代码，
区别只在"视觉审查"那一步是人工还是自动。

```text
                ┌─────────────────────────────────────────────────┐
                │  输入：RGB + prompt (+ 可选 category/task/...)   │
                └────────────────────┬────────────────────────────┘
                                     ↓
                          ┌──────────────────────┐
                          │  AssetStore.create   │  ← 写 manifest + 受控副本
                          └──────────┬───────────┘
                                     ↓
                          ┌──────────────────────┐
                          │  Loop 1: 视觉生成     │
                          │  SAM3 → SAM3D → 静态 │
                          │  mask/几何检查        │
                          │  + 失败自动重试        │
                          │  (sam3d seed × 3)     │
                          └──────────┬───────────┘
                                     ↓
                          ┌──────────────────────┐
                          │  status=review_required │
                          └──────────┬───────────┘
                                     ↓
                ┌────────────────────┴────────────────────┐
                ↓                                         ↓
    ┌───────────────────────┐               ┌───────────────────────┐
    │ 路径 A:  Gradio UI    │               │ 路径 B:  CLI (本文档)   │
    │ launch_asset_agent.py│               │ run_pipeline.py        │
    │                       │               │                        │
    │ 人工在浏览器里:        │               │ 自动调:                 │
    │  - 看 mask/GLB 预览   │               │  ReviewDecision        │
    │  - 看几何报告         │               │  (approved=True)       │
    │  - 点"批准"按钮       │               │  → 跳过人工审查         │
    │  → ReviewDecision     │               │                        │
    │  (approved=True)      │               │                        │
    └───────────┬───────────┘               └───────────┬────────────┘
                ↓                                         ↓
                └────────────────────┬────────────────────┘
                                     ↓
                          ┌──────────────────────┐
                          │ submit_review(       │
                          │   approved=True)     │
                          └──────────┬───────────┘
                                     ↓
                          ┌──────────────────────┐
                          │  begin_physics_review │
                          │  → PHYSICS_REVIEW_    │
                          │    RUNNING            │
                          └──────────┬───────────┘
                                     ↓
                ┌────────────────────┴────────────────────┐
                ↓ Loop: 最长 3 轮                          ↓
    ┌───────────────────────┐               ┌───────────────────────┐
    │ PhysicsAuthorAgent    │  写 spec  →   │ PhysicsCriticAgent    │
    │ (规则 agent, 可换 LLM)│               │ (规则 agent, 可换 LLM) │
    └───────────────────────┘               └───────────┬───────────┘
                ↑                                         │
                │ revise(spec, findings)                  │ review(spec)
                │                                         │
                └─────────────────────────────────────────┘
                                     ↓ (critic 接受)
                          ┌──────────────────────┐
                          │  run_usd_authoring   │
                          │  convert → prepare → │
                          │  apply_material →    │
                          │  inspect             │
                          └──────────┬───────────┘
                                     ↓
                          ┌──────────────────────┐
                          │ status=complete      │
                          │ final/asset.usd  ✓   │
                          └──────────────────────┘
```

---

## 3. 状态机

```
         ┌─────────────┐
         │   CREATED   │
         └──────┬──────┘
                ↓ run_visual()
         ┌─────────────┐
         │VISUAL_RUNNING│
         └──────┬──────┘
                ↓
         ┌─────────────────┐  reject+issue     ┌──────────────────┐
         │ REVIEW_REQUIRED │ ─────────────────→│ VISUAL_RUNNING   │
         └────────┬────────┘                   │ (受控修复)        │
                  │ approve                    └──────────────────┘
                  ↓
         ┌───────────────────────┐
         │ PHYSICS_REVIEW_RUNNING│  ← 中间短暂 VISUAL_APPROVED
         └────────┬──────────────┘
                  ↓
        ┌─────────┴─────────┐
        ↓                   ↓
┌──────────────┐    ┌──────────────┐
│ USD_RUNNING  │    │   BLOCKED    │  ← Critic 3 轮不收敛
└──────┬───────┘    └──────────────┘
       ↓
┌──────────────┐
│  COMPLETE    │  ← 写出 final/asset.usd
└──────────────┘

   任意状态可 → FAILED
   FAILED 可 → VISUAL_RUNNING（重试）
   BLOCKED / COMPLETE → 终态
```

终态判断（CLI 用）：

| manifest["status"] | CLI 退出码 | 含义 |
|---|---|---|
| `complete` | 0 | `final/asset.usd` 存在 |
| `blocked` | 2 | Author/Critic 3 轮未收敛，未生成 USD |
| `failed` | 1 | 任一步骤抛异常 / schema 检查未通过 |
| 其他 | 1 | 未预期的中间态（异常） |

---

## 4. CLI 用法

### 4.1 安装与配置

前置环境：
- `sam3` conda 环境（含 PyTorch + SAM3 checkpoint）
- `sam3d-objects` conda 环境（含 SAM3D 权重 + 推理）
- Isaac Sim 5.1 安装目录（含 `python.sh`）

环境变量：

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL CONDA_PROMPT_MODIFIER
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
export ISAAC_SIM_PATH=/abs/path/to/isaac-sim-5.1.0
export SAM3_CHECKPOINT_DIR=/abs/path/to/checkpoints/sam3  # 含 sam3.pt
# 可选：export SAM3D_CHECKPOINT_DIR=...
# 可选：export PIPELINE_OUTPUT_DIR=/abs/path/to/outputs
```

> ⚠️ `unset CONDA_*` 一定要做，否则 Isaac Sim 的 `python.sh` 会拒绝运行
> （参考 `docs/asset_usd_pipeline.md` §6.1）。

### 4.2 命令

```bash
python scripts/run_pipeline.py \
  --image /abs/path/to/red_mug.jpg \
  --prompt "a red mug" \
  --asset-category cup
```

完整参数：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--image` | 必填 | 输入 RGB 图绝对路径 |
| `--prompt` | 必填 | 文本 prompt（SAM3 用来选 mask） |
| `--asset-category` | `""` | 可选；帮助 policy 推断材质/碰撞 profile |
| `--target-task` | `""` | 可选；写进 manifest 元数据 |
| `--robot-constraints` | `""` | 可选；写进 manifest 元数据 |
| `--output-root` | `$PIPELINE_OUTPUT_DIR` 或 `./outputs` | asset bundle 根目录 |
| `--isaac-sim-path` | `$ISAAC_SIM_PATH` | Isaac Sim 安装目录（含 python.sh） |
| `--sam3-env` | `sam3` | SAM3 的 conda 环境名 |
| `--sam3d-env` | `sam3d-objects` | SAM3D 的 conda 环境名 |
| `--rewrite-prompt` | false | 用规则改写 `--prompt` 后再喂给 SAM3（见 §4.5） |
| `--quiet` | false | 只打最终结果，不打阶段进度 |

退出码：

| 退出码 | 含义 |
|---|---|
| `0` | COMPLETE，`final/asset.usd` 已写出 |
| `2` | BLOCKED，Author/Critic 3 轮未收敛，stderr 打印 critic findings |
| `1` | FAILED 或参数错误 |

### 4.3 失败时的诊断输出

CLI 失败时会从 stderr 输出 Physics Critic 的 findings，方便无 UI 调试：

```
Loop 1 visual generation failed: sam3 failed
[20:59:01] ...
```

或 BLOCKED 时：

```
Physics Author/Critic did not converge within 3 rounds; status=blocked; USD was not authored.
  Critic findings:
  - physics_review_001.json (round 1): Rejected with 2 deterministic finding(s).
      [error] collision.container_sealed: convexHull seals a container opening; use sdf or convexDecomposition.
      [error] material.invalid: ...
  ...
```

### 4.4 已知限制

| 限制 | 影响 | 缓解 |
|---|---|---|
| SAM3 对抽象 prompt 不友好 | "a platform trolley" → 0 candidates | 加 `--rewrite-prompt` 启用规则改写（见 §4.5），或改具体描述 |
| `policy.physics_proposal` 是规则化推断 | 非 cup/mug 类物体可能落到 generic profile | 后续可加 `--material` / `--collision` flag 显式覆盖 |
| 与 Gradio UI 共享 `outputs/` | 并发会冲突 | 后续可加 CLI 专属 `--output-root` 默认值 |
| Isaac Sim 子进程依赖真实环境 | 单测用 `FakeRunner` + 占位 `python.sh` 模拟 | 见 `tests/unit/test_cli_pipeline.py` |

### 4.5 Prompt 改写（缓解 SAM3 抽象 prompt 脆弱性）

`--rewrite-prompt` flag 启用一个**纯函数、无 LLM 依赖**的关键词映射，
把抽象/领域名词改成 SAM3 训练时见过的具体描述。

```bash
# 原本会 0 candidates
python scripts/run_pipeline.py \
  --image ... --prompt "a platform trolley" --asset-category trolley
# 输出：[rewriter] 'a platform trolley' -> 'a flatbed cart with handle and wheels'
# 然后 SAM3 用改写后的 prompt 跑
```

映射表覆盖常用矿业/容器/工具关键词：trolley / cart / drill / excavator /
ore / rock / bucket / container / hammer / pipe / ... 共 30+ 条。

源代码：`src/mining_asset_pipeline/agent/prompt_rewriter.py`
单测：`tests/unit/test_prompt_rewriter.py`（覆盖命中、case-insensitive、
whole-word 避免 substring 误命中、空输入 fallback 等）

**何时升级到 LLM**：当 `--rewrite-prompt` 仍命中不到你想用的名词时，
调用方可以传入更具体的 `--prompt`，或者后续接入 Claude API 做
semantic rewrite（接口已经留好——只换 `rewrite_prompt()` 内部即可）。

---

---

## 5. 实测样例

### 5.1 红色马克杯（重做）

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL CONDA_PROMPT_MODIFIER
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
export ISAAC_SIM_PATH=/home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0
export SAM3_CHECKPOINT_DIR=/home/user/Xsb_WS/Benchmark/Assest_maker/checkpoints/sam3

python scripts/run_pipeline.py \
  --image /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/images/red_mug.jpg \
  --prompt "a red mug" \
  --asset-category cup
```

退出码 `0`，最终：
```
outputs/<timestamp>-cup-<hash>/final/asset.usd
```
≈ 16 MB，density 2500 kg/m³，collision=sdf。

### 5.2 平台小推车（test001，2026-07-12 首次跑通）

```bash
python scripts/run_pipeline.py \
  --image /home/user/Xsb_WS/test001/小推车.jpg \
  --prompt "a flatbed cart with handle and wheels" \
  --asset-category trolley
```

退出码 `0`，总耗时 ~1m37s，最终：

```
outputs/20260712-210019-trolley-da678b/final/asset.usd
```

| 阶段 | 耗时 | 状态 |
|---|---|---|
| 视觉生成 (SAM3 + SAM3D) | ~56s | pass |
| 物理审查 (Author + Critic) | ~41s | accepted |
| USD 物理化 | <1s | all 4 checks ok |

> **第一次用 "a platform trolley" 跑失败**（SAM3 0 candidates）。
> 改成具体描述后立刻识别成功。
> 这是当前**最脆弱**的一步；后续可接 LLM 自动改写 prompt。

---

## 6. 复跑命令

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL CONDA_PROMPT_MODIFIER
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
export ISAAC_SIM_PATH=/home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0
export SAM3_CHECKPOINT_DIR=/home/user/Xsb_WS/Benchmark/Assest_maker/checkpoints/sam3

python scripts/run_pipeline.py \
  --image <RGB_PATH> \
  --prompt "<PROMPT>" \
  --asset-category <CATEGORY>
```

---

## 7. 跟 Gradio UI 的对比

| 维度 | CLI | Gradio UI |
|---|---|---|
| 启动 | `python scripts/run_pipeline.py --image ... --prompt ...` | `python scripts/launch_asset_agent.py` |
| 视觉审查 | **跳过**（自动 approve） | **人工** 看 mask/GLB 预览 + 反馈 |
| 物理审查 | 自动多轮（Author/Critic） | 自动多轮（Author/Critic） |
| USD 化 | 自动 | 自动 |
| 输出 | `final/asset.usd` + 退出码 | `final/asset.usd` + Gradio UI 状态 |
| 适合 | CI / 批处理 / Agent 调用 | 交互调试 / 视觉质量验证 |
| 入口脚本 | `scripts/run_pipeline.py` | `scripts/launch_asset_agent.py` |
| 业务核心 | `AssetWorkflow.submit_review(approved=True)` | 同左 |

两条路径**共享同一份**业务代码（`src/mining_asset_pipeline/agent/`），
改一处两边受益。

---

## 8. 当前工作流的能力边界

| 已实现 | 未实现 |
|---|---|
| 单图 + 单 prompt → USD | 多视角输入 / 多物体批量分割 |
| 自动视觉审查（mask/几何检查） | 视觉一致性回比（多角度渲染 vs RGB） |
| SAM3D seed 自动重试 3 次 | 几何修复（自交/长薄面/退化三角面自动修） |
| Physics Author/Critic 多轮协商（规则 agent） | Critic 接 LLM（接口已留 `LLMPolicyAdapter`） |
| Isaac Sim 5.1 USD 静态 schema 校验 | 动态仿真回归（drop/push/grasp/stack） |
| CLI 退出码 + critic findings 诊断 | Web UI / REST API 服务化 |

详细 TODO 见 README.md 与 `docs/architecture.md`。

---

## 9. 后续可做的工作

按价值/工作量排序：

| 优先级 | 工作 | 工作量 | 价值 |
|---|---|---|---|
| 1️⃣ | 写 `.claude/skills/mining-asset-pipeline/SKILL.md` | 10 分钟 | 让 Claude Code 会话自动识别"我要跑 pipeline" |
| 2️⃣ | 加 `scripts/batch_pipeline.py`（一次跑 N 张图） | 1 小时 | 矿业数据集准备 |
| 3️⃣ | `PhysicsCriticAgent` 切换到 Claude API | 2 小时 | Critic 更智能，能处理更多物体 |
| 4️⃣ | 自动 prompt 改写（解决"0 candidates"脆弱性） | 半天 | CLI 鲁棒性显著提升 |
| 5️⃣ | Loop 2 动态仿真 `tests/simulation/drop_test.py` | 1 周+ | USD 从"schema 通过"到"真正可用" |

---

## 10. 引用清单

| 来源 | 用途 |
|---|---|
| `src/mining_asset_pipeline/agent/workflow.py` | 业务核心 `AssetWorkflow` |
| `src/mining_asset_pipeline/agent/storage.py` | `AssetStore` + 状态机迁移 |
| `src/mining_asset_pipeline/agent/physics_agents.py` | PhysicsAuthor / PhysicsCritic 规则 agent |
| `src/mining_asset_pipeline/agent/models.py` | `AssetRequest` / `AssetStatus` / `VALID_TRANSITIONS` |
| `scripts/run_pipeline.py` | 本文档描述的 CLI 入口 |
| `scripts/launch_asset_agent.py` | Gradio UI 入口（参照路径 A） |
| `docs/asset_quality_agent.md` | Gradio UI 工作流详细说明 |
| `docs/asset_usd_pipeline.md` | Loop 2 USD 化试跑记录 |
| `docs/architecture.md` | 仓库整体布局与策略 |
| `tests/unit/test_cli_pipeline.py` | CLI 单测（FakeRunner + 退出码断言） |

---

*文件创建于 2026-07-12。下次如要做 Skill / Claude API / 批处理，本文档是事实底稿。*