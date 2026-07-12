# 项目接手说明（Handoff）

> 写给接手这个 Mining Asset Pipeline 项目的 Agent。
> 截止 2026-07-13，main 分支上已完成的工作、为什么这么做、以及接下来建议做什么。

---

## 1. 项目一句话

把 **RGB 图 + 文本 prompt** 转成 **可在 NVIDIA Isaac Sim 5.1 直接落桌/抓取的 USD 资产**。矿业场景（矿卡、钻机、矿石堆）为主要目标，红杯样例已端到端跑通。

代码仓库根目录：`/home/user/Xsb_WS`（git main 分支）。

---

## 2. 当前已经做好的（不要再造轮子）

### 2.1 业务核心（src/mining_asset_pipeline/agent/）

| 文件 | 作用 | 关键 public API |
|---|---|---|
| `models.py` | 数据类 + 状态机 | `AssetRequest`, `ReviewDecision`, `AssetStatus`, `VALID_TRANSITIONS` |
| `storage.py` | 资产 bundle 持久化 | `AssetStore.create / manifest / transition / fail / set_artifact / archive_visual` |
| `workflow.py` | 端到端编排 | `AssetWorkflow.create_asset / run_visual / submit_review / begin_physics_review / run_physics_pipeline / summary` |
| `inspection.py` | 静态检查 | `inspect_sam3`, `inspect_glb`, `select_sam3_candidate`（不依赖 trimesh） |
| `policy.py` | 规则推断 | `RuleBasedPolicy.repair_action`, `physics_proposal`；LLM 扩展点 `LLMPolicyAdapter` 占位 |
| `physics_agents.py` | 自动物理审查 | `PhysicsAuthorAgent.initial_spec / revise`, `PhysicsCriticAgent.review`, `PhysicsReview` dataclass |
| `runner.py` | 子进程隔离 | `SubprocessToolRunner.run / stream`（流式基于 Popen） |
| `prompt_rewriter.py` | 关键词 → SAM3 友好 prompt | `rewrite_prompt(prompt, category) -> str`，纯函数，30+ 矿业关键词映射 |
| `web.py` | Gradio UI | `build_demo(workflow) -> Blocks`，含 SVG 进度条 + gr.Timer 日志轮询 + 资产列表 |
| `usd/*.py` | USD 工具实现 | 被 `scripts/_run_usd_tool.py` 转发 |

### 2.2 入口（scripts/）

| 脚本 | 用途 |
|---|---|
| `run_sam3.py` | SAM3 文本→mask（`sam3` conda 环境） |
| `run_sam3d.py` | SAM3D 单图→GLB/OBJ/PLY（`sam3d-objects` conda 环境） |
| `convert_to_usd.py` / `prepare_physics.py` / `apply_physics_material.py` / `inspect_physics.py` / `validate_asset.py` | USD 工具（Isaac Sim `python.sh` 调用） |
| `launch_asset_agent.py` | Gradio UI 启动器（人工审查路径） |
| **`run_pipeline.py`** | **无人值守 CLI**（核心入口） |
| `launch_isaac_sim.sh` | 启动 Isaac Sim 桌面 UI |

### 2.3 CLI（run_pipeline.py）用法

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL CONDA_PROMPT_MODIFIER
unset PYTHONPATH PYTHONHOME LD_LIBRARY_PATH
export ISAAC_SIM_PATH=/path/to/isaac-sim-5.1.0
export SAM3_CHECKPOINT_DIR=/path/to/checkpoints/sam3

python scripts/run_pipeline.py \
  --image <RGB_PATH> \
  --prompt "<PROMPT>" \
  --asset-category <CATEGORY> \
  [--rewrite-prompt]    # 启用 prompt 改写缓解 SAM3 0 candidates
  [--quiet]
```

**退出码**：`0` COMPLETE（`final/asset.usd` 已生成）/ `2` BLOCKED / `1` FAILED。
**实测**：`/home/user/Xsb_WS/test001/小推车.jpg` + `"a flatbed cart with handle and wheels"` + `--asset-category trolley` → 1m37s 跑通，16MB USD。

### 2.4 状态机（manifest.json["status"]）

```
CREATED → VISUAL_RUNNING → REVIEW_REQUIRED
                          ├─ reject → VISUAL_RUNNING（rerun_sam3 / rerun_sam3d / human_input_required）
                          └─ approve → PHYSICS_REVIEW_RUNNING → USD_RUNNING → COMPLETE
任何状态可 → FAILED / BLOCKED
FAILED 可 → VISUAL_RUNNING 重试
```

### 2.5 资产 bundle 布局

```
outputs/<timestamp>-<slug>-<shortid>/
├── manifest.json + request.json
├── input/source.jpg + metadata.json
├── visual/{sam3/, sam3d/, sam3_report.json, geometry_report.json, review.json}
├── physics/
│   ├── physics_proposal.json + physics_spec.yaml + physics_spec_revision_00X.yaml
│   ├── physics_review_00X.json  ← Critic 评分，每轮一份
│   ├── visual.usd + physics.usd + simulation_ready.usd + material_report.json
│   └── inspection.json + logs/{convert, prepare_physics, apply_material, inspect}.log
├── final/asset.usd + asset_report.json
└── history/visual_XXX/  ← 被替换的旧视觉版本
```

### 2.6 配置

| 路径 | 作用 |
|---|---|
| `configs/materials/{ceramic, generic}.yaml` | 密度/摩擦/弹性 |
| `configs/collision_profiles/{open_container, generic_solid}.yaml` | collision 近似 |
| `configs/physics_spec_template.yaml` | PhysicsAuthor agent 用的 spec 模板 |

### 2.7 测试

`python -m unittest discover -s tests/unit` — **31/31 全绿**。

- `test_asset_agent.py`（9 测试）：workflow / store / policy / FakeRunner 覆盖
- `test_repository_layout.py`（3 测试）：仓库契约
- `test_web_helpers.py`（7 测试）：SVG 渲染 / 资产扫描 / log tail / UI 13 元 tuple
- `test_cli_pipeline.py`（3 测试）：CLI argparse + COMPLETE + BLOCKED 分支
- `test_prompt_rewriter.py`（10 测试）：关键词命中、case、whole-word 等

**`tests/integration/` 和 `tests/simulation/` 都是空目录**。

### 2.8 文档（docs/）

| 文件 | 用途 |
|---|---|
| `architecture.md` | 仓库整体布局、依赖策略、legacy 迁移 |
| `setup.md` | 安装 + submodule + 模型权限 |
| `sam3_to_sam3d_pipeline.md` | Loop 1 试跑记录（5 个真坑） |
| `asset_usd_pipeline.md` | Loop 2 USD 化试跑记录 |
| `apply_physics_material.md` | `apply_physics_material.py` 参数权威手册 |
| `asset_quality_agent.md` | Gradio UI 工作流 |
| `cli_pipeline.md` | **无人值守 CLI 详细文档**（最权威） |
| `e2e_red_mug_validation.md` | 重构后端到端验证 |
| `legacy_workspace_setup.md` | 旧 workspace 部署 |
| `handoff.md` | **本文档** |

---

## 3. 关键设计决策（为什么这样做）

1. **3 个分离的 conda 环境**：SAM3（`sam3`，PyTorch 2.9 + CUDA 12.8）、SAM3D（`sam3d-objects`）、基础 Python（项目主环境）。Isaac Sim 必须 `unset CONDA_*` 后用 `python.sh` 调。详见 `sam3_to_sam3d_pipeline.md` §6.1。

2. **状态机用 dict-of-set**：`VALID_TRANSITIONS[AssetStatus]` 显式列举合法迁移。CLI/UI 共用同一份状态机，单测覆盖非法迁移抛 ValueError。

3. **拒绝分支时受控修复**：`policy.repair_action(decision)` 只返回 3 种动作（`rerun_sam3` / `rerun_sam3d` / `human_input_required`），不做几何修补或纹理编辑。其他 issue 一律转人工。

4. **Physics Author/Critic 多轮协商**：最多 3 轮不收敛就 BLOCKED。Author 写 spec，Critic 检查（含 9 条规则如 collision 不能封住 cup 口）。**接口已留 `LLMPolicyAdapter`**，未来换 LLM Critic 只改 `physics_agents.py`，`workflow.py` 不动。

5. **持久化全 JSON**：bundle 内所有状态可读、可 diff、可回放。manifest 包含事件历史（时间戳 + status + message）。

6. **Prompt rewriter 是纯函数**：`src/mining_asset_pipeline/agent/prompt_rewriter.py:rewrite_prompt(prompt, category) -> str`。零依赖、deterministic、可单测。升级到 Claude API 时只换内部实现，签名不变。

7. **CLI 与 Gradio UI 共享业务代码**：两条路径都通过 `AssetWorkflow.submit_review(approved=True)` 触发后续，区别只在"人工按按钮 vs 自动调"。

---

## 4. 后续建议做的工作（按价值排序）

接手 Agent 应该优先做什么，按价值/工作量比排：

### 4.1 🔴 高价值

| # | 工作 | 工作量 | 价值 |
|---|---|---|---|
| 1 | 接 LLM 到 `PhysicsCriticAgent` —— 用 Claude API 替代规则 critic | 半天 | Critic 智能度跃升，能处理矿业专属物体 |
| 2 | 加 `scripts/batch_pipeline.py` —— 一次跑 N 张图（manifest 驱动） | 1-2 小时 | 矿业数据集准备、回归测试 |
| 3 | **写 `.claude/skills/mining-asset-pipeline/SKILL.md`** | 10 分钟 | Claude Code 会话自动识别"我要跑 pipeline" |
| 4 | 加矿业专属 material/collision profile（钢 7850、铁矿 5000、橡胶 1100） | 2 小时 | 当前只有 ceramic + generic + open_container |

### 4.2 🟡 工程债

| # | 工作 | 工作量 |
|---|---|---|
| 5 | 真实环境集成测试 —— `tests/integration/` 加 1-2 条真 SAM3/SAM3D | 半天 |
| 6 | Loop 2 动态仿真回归 —— `tests/simulation/drop_test.py` | 1 周+ |
| 7 | CLI `--material` / `--collision` flag —— 用户显式覆盖 policy 推断 | 半小时 |
| 8 | CLI 退出后清理机制 —— `--keep-bundle` / `--clean-on-fail` | 半小时 |

### 4.3 🟢 可选增强

| # | 工作 | 工作量 |
|---|---|---|
| 9 | Claude API 升级 `prompt_rewriter` | 半天 |
| 10 | REST API 服务化（FastAPI） | 1 天 |
| 11 | Web UI 加"自动模式" toggle（Gradio checkbox） | 10 分钟 |
| 12 | 视觉一致性回比（多角度渲染 vs RGB） | 1 周 |
| 13 | `docs/` 加架构图（mermaid 状态机 + 双入口路径） | 半天 |

### 4.4 🚪 收尾（可选）

| # | 工作 | 工作量 |
|---|---|---|
| 14 | 清理 outputs/ —— 保留 `20260712-210019-trolley-da678b` 作 demo | 5 分钟 |
| 15 | 合并/归档 feature branch | 5 分钟 |
| 16 | 更新 README.md Status 章节 —— 写"已验证含红杯 + 推车" | 5 分钟 |

---

## 5. 接手时要小心的陷阱

1. **`unset CONDA_*` 不能忘**：Isaac Sim `python.sh` 检测到 conda 就拒绝运行。任何调 Isaac Sim 的脚本都必须在子 shell 里清掉这些变量。详见 `docs/asset_usd_pipeline.md` §6.1。

2. **SAM3 dtype mismatch**：Ada (RTX 4090) GPU 上 SAM3 的 `sam3.perflib.fused.addmm_act` 硬转 bf16，叠加 `decoder.forward_ffn` 的 autocast(False) 强制 fp32 会炸。`scripts/run_sam3.py:75-86` 已经 monkey-patch 了，**别动这部分**。

3. **SAM3D `sam3d_objects` 包未 pip install**：`run_sam3d.py` 用 `sys.path.append("notebook")` 直跑，不要试图 `pip install -e .`（会缺 init.py）。

4. **httpx socks 代理**：`run_sam3d.py` 开头改写 `ALL_PROXY=socks://` → `http://`，gradio 在 import 时构造 httpx.Client 触发的。如果环境变了要看一下。

5. **`addmm_act` monkey-patch 时机**：`scripts/run_sam3.py:83-85` 在 import 后立即 patch，且要 patch 两处（`sys.modules["sam3.perflib.fused"]` 和 `sam3.model.vitdet`），缺一会炸。

6. **Isaac Sim 真实环境才能跑 USD 步骤**：CLI 集成测试用 `FakeRunner` + 占位 `python.sh`（见 `test_cli_pipeline.py`）。生产路径必须真 Isaac Sim 5.1。

7. **`outputs/` 不会被 git 跟踪**（`.gitignore` 已加 `/outputs/`），但 `Benchmark/Assest_maker/outputs/` 是 legacy workspace 的一部分，也已忽略。

8. **状态机迁移是显式枚举**：`VALID_TRANSITIONS` 列出所有合法迁移。要加新状态必须同时改 `models.py`、`VALID_TRANSITIONS`、`storage.transition`、`web._PROGRESS`、单测。

9. **`AssetRequest` 是 frozen dataclass**：要改字段必须改 dataclass 定义 + 所有调用点。

10. **PhysicsAuthor/Critic 多轮规则**：`physics_agents.py:104-105` 有 "container + convexHull → 自动改成 sdf" 这种自纠逻辑。如果未来 spec schema 改了，要同步检查。

---

## 6. 接手建议

1. **先读 `docs/cli_pipeline.md`**（最权威，含状态机、CLI 用法、实测、后续工作）
2. **再读 `docs/architecture.md`**（仓库布局 + 依赖策略）
3. **跑 `python -m unittest discover -s tests/unit`** 确认 31 测试全绿
4. **跑一次完整 CLI**：`scripts/run_pipeline.py --image test001/小推车.jpg --prompt "a flatbed cart with handle and wheels" --asset-category trolley --rewrite-prompt`，预期 1m 左右出 `final/asset.usd`
5. **从 §4.1 高价值任务挑一个开始**：建议 #3 SKILL.md（10 分钟）或 #2 batch_pipeline.py（1-2 小时）

---

*文档写于 2026-07-13。如接手 Agent 发现本文档与代码不符，以代码为准并更新本文档。*