<div align="center">

# ⛏️ Mining Asset Pipeline

### 从视觉输入到可移植、物理化的 USD

[![Status: Experimental](https://img.shields.io/badge/status-experimental-7C3AED?style=flat-square)](CHANGELOG.md)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-2563EB?style=flat-square)](LICENSE)
[![Isaac Sim](https://img.shields.io/badge/Isaac%20Sim-5.1-76B900?style=flat-square)](https://developer.nvidia.com/isaac/sim)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square)](pyproject.toml)

[English](README.md) · [简体中文](README.zh-CN.md)

</div>

> **从单张 RGB 图片或环绕视频，得到可移植的 USD 包。**
> 资产路径结合 Meta SAM3、SAM 3D Objects、受限质量 Agent 和 NVIDIA Isaac
> Sim 5.1；场景路径将 Marble 导出组装为静态 Real2Sim Phase 1 场景包。

```text
RGB + prompt  ──► 已审查、物理化的资产 USD
视频/全景图    ──► Marble + Phase 1 ──► 可移植场景 USD
```

> **项目状态：** 实验性 `v0.2.0`。流程会写入几何、渲染颜色、刚体、质量/密度、
> 碰撞、摩擦、弹性、阻尼与 CCD，并进行静态 USD 检查。动态落体、推挤和抓取验证
> 属于后续 Loop 2，因此当前的“完成”仅表示**静态流程完成**，不表示已通过仿真任务认证。

## 快速开始：选择入口

请先完成共享机器环境配置：[docs/setup.md](docs/setup.md)，再按输入和自动化程度选择入口。

| 目标 | 输入 | 推荐入口 | 额外要求 |
|---|---|---|---|
| 生成单个仿真资产 | RGB 图片 + 粗略提示词 | 在 Codex/Claude Code 使用 `$generate-mining-asset` | SAM3、SAM3D、权重、Isaac Sim |
| 批量生成仿真资产 | JSON 批处理清单 | `python scripts/batch_pipeline.py --manifest ...` | 与资产流程相同 |
| 生成静态 Phase 1 场景 | 环绕视频或全景图 | 在 Codex/Claude Code 使用 `$generate-mining-scene` | `.[scene]`、`worldcomposer-r2s`、Isaac Sim、`WORLDLABS_API_KEY` |
| 无人值守生成单个资产 | RGB 图片 + 提示词 | `python scripts/run_pipeline.py ...` | 内置 Controller 需要可选 `.[llm]` 与 `ANTHROPIC_API_KEY` |

仓库 Skill 使用当前 Codex/Claude Code 会话自身的推理能力，不读取项目级 Anthropic
密钥。场景流程仅覆盖静态 Phase 1，不验证机器人动力学、导航或任务成功。

## 已实现能力

```text
RGB + prompt
  → SAM3 文本条件分割
  → SAM 3D Objects 三维重建（GLB）
  → 语义视觉 Agent 审查与有限修复
  → 独立 Physics Author / Critic 审查与确定性否决
  → GLB → visual.usd → physics.usd → simulation_ready.usd
  → 静态物理检查 → final/<object_name>.usd
```

- 支持单资产和批量命令行工作流。
- 批处理为每个输入创建隔离的输出包。
- 有两种控制平面：Codex/Claude Code 仓库 Skill，以及用于无人值守的内置 Claude API Controller。
- 可选 API 不可用时使用确定性专用 fallback；泛化物体不会被静默放行。
- 容器感知的碰撞策略选择（`sdf`/`convexDecomposition`）。
- 通过 USD Preview Surface 保留 SAM3D 顶点颜色。
- 保存 manifest、检查报告、工具日志和 Physics Review 记录。
- Real2Sim Phase 1：Marble PLY + collider GLB → 可移植、可渲染的场景 USD；只有明确要求时才导出 HQ 贴图网格。

## 仓库结构

| 路径 | 职责 |
|---|---|
| `src/mining_asset_pipeline/` | 可复用编排与 USD 工具 |
| `scripts/` | 受支持的命令行入口 |
| `configs/` | 材质与碰撞 profile |
| `assets/samples/` | 小型、授权清晰的复现输入 |
| `tests/` | 无重依赖单元测试和未来 GPU/仿真测试 |
| `third_party/` | 固定版本的 SAM3、SAM 3D Objects、3dgrut、WorldComposer 子模块 |
| `docs/` | 安装、架构、工作流与实验记录 |
| `Benchmark/` | 被忽略的历史/本地运行兼容目录 |

模型权重、Isaac Sim、生成的 GLB/USD 文件和 API 凭据均不会存入 Git。

资产流程和场景流程互相独立。场景的 Phase 1 安装、输出包与验证边界参见
[Marble scene → USD](docs/scene_pipeline.md)。

## 系统要求

- Linux x86-64（已在 Ubuntu 22.04 验证）。
- 编排环境使用 Python 3.11。
- SAM3 需要 Conda；固定的上游 SAM3D 安装步骤还需要 Mamba；两者均使用独立环境。
- NVIDIA GPU 与相应驱动；SAM 3D Objects 上游建议至少 32 GB 显存。
- 本地安装 NVIDIA Isaac Sim 5.1。
- 资产流程需要能访问 Hugging Face 上受限的 SAM3 和 SAM 3D Objects 权重。

上游源码版本由 `.gitmodules` 和 Git 子模块固定。GPU 结果仍可能因驱动和模型内核
变化而不同；保存的 manifest 与验证报告是可复现性的边界。

## 安装

### 1. 克隆源码与固定子模块

```bash
git clone --recurse-submodules <repository-url>
cd Mining-Asset-Pipeline
```

已有 clone 时运行：

```bash
scripts/update_submodules.sh
```

### 2. 创建编排环境

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

按需安装可选功能：

```bash
python -m pip install -e '.[llm]'     # 内置无人值守 Claude Controller
python -m pip install -e '.[scene]'   # World Labs Marble 场景客户端
```

推荐以源码 checkout 部署，因为完整应用还需要仓库配置、脚本和 Git 子模块。构建出的
wheel 只包含可复用 Python 包，不会打包模型代码、权重、Isaac Sim 或面向用户的样例。

### 3. 安装模型环境

SAM3 使用固定上游版本指定的环境：

```bash
conda create -n sam3 python=3.12 -y
conda run -n sam3 pip install torch==2.10.0 torchvision \
  --index-url https://download.pytorch.org/whl/cu128
conda run -n sam3 pip install -e third_party/sam3
```

SAM 3D Objects 需要更大的 CUDA/PyTorch3D 环境。请在仓库根目录遵循固定子模块中的
[`doc/setup.md`](third_party/sam-3d-objects/doc/setup.md)，并保留环境名
`sam3d-objects`。

### 4. 下载受限权重

使用自己的 Hugging Face 账号认证；不要将 token 写入本仓库。

```bash
hf auth login
hf download facebook/sam3 --local-dir checkpoints/sam3

cd third_party/sam-3d-objects
hf download --repo-type model --local-dir checkpoints/hf-download \
  --max-workers 1 facebook/sam-3d-objects
mv checkpoints/hf-download/checkpoints checkpoints/hf
cd ../..
```

期望文件：

```text
checkpoints/sam3/sam3.pt
third_party/sam-3d-objects/checkpoints/hf/pipeline.yaml
```

### 5. 配置本地路径并验证机器

```bash
cp environments/local.env.example environments/local.env
# 编辑路径后加载：
source environments/local.env

python scripts/doctor.py
```

`doctor.py` 会在不加载 GPU 模型的情况下检查 Python 包、两个 Conda 环境、子模块、
权重、NVIDIA 工具和 Isaac Sim 安装。

完整细节和故障排查请见 [docs/setup.md](docs/setup.md)。

## 运行流程

### 可复现资产样例

```bash
source .venv/bin/activate
source environments/local.env

python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

最终路径会以 `final_usd=...` 输出。完整资产包写入 `outputs/<asset-id>/`。

运行两个授权样例：

```bash
python scripts/batch_pipeline.py \
  --manifest assets/samples/batch_manifest.json \
  --continue-on-error
```

### 仓库 Skill：生成单个资产（无需项目 API 调用）

在 Codex 或 Claude Code 中打开仓库，并输入：

```text
Use $generate-mining-asset with RGB /absolute/path/object.png
and rough prompt "a rusty mining drill rod"
```

规范正文位于 `.agents/skills/generate-mining-asset`；其受控工具不会 import
Anthropic，也不会读取 `ANTHROPIC_API_KEY`。

### 仓库 Skill：生成一个 Phase 1 场景

安装场景依赖，并在启动 Agent 的 shell 中配置 World Labs 凭据。不要将凭据写入仓库文件。

```bash
python -m pip install -e '.[scene]'
scripts/setup_scene_phase1_env.sh
export WORLDLABS_API_KEY='your-key-in-the-shell-only'
```

接着提供一个本地环绕视频（`.mp4`、`.mov`、`.mkv`）或一张全景 RGB 图片。版本控制的
拍摄样例是 `assets/samples/scenes/mine_tunnel_orbit.mp4`：

```text
Use $generate-mining-scene with assets/samples/scenes/mine_tunnel_orbit.mp4
and description "a subterranean mine tunnel"
```

该 Skill 会获取 Marble 导出、组装 Phase 1、检查静态 USD 报告并渲染短预览，然后才返回
最终场景 USD。默认使用 PLY/NuRec 路径；仅在明确要求时导出 HQ 贴图网格。成本、拍摄、
输出包与限制详见 [Marble scene → USD](docs/scene_pipeline.md)。

### 内置 Claude Controller

```bash
python -m pip install -e '.[llm]'
export ANTHROPIC_API_KEY='your-key-in-the-shell-only'
export ANTHROPIC_MODEL='a-model-available-to-your-account'

python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

没有启用开关或 CLI key 参数。Controller 只从环境读取密钥；如果 SDK、密钥、API、响应或
网络失败，工作流会记录 fallback。只有具备专用确定性 profile 的资产才可能以
`quality=degraded` 交付，泛化物体会被阻断。

## 输出契约

```text
outputs/<asset-id>/
├── manifest.json
├── request.json
├── agent/         # 语义 brief、结构化决策、trace
├── input/
├── visual/        # 不可变的 SAM3/SAM3D 尝试与选中的审查记录
├── physics/       # Author/Critic 记录、USD 阶段、静态检查
└── final/
    ├── <object_name>.usd
    └── asset_report.json
```

manifest 内所有路径均相对于资产包。Manifest v3 分离了 status、phase 与 quality。退出码：
完成是 `0`，阻断是 `2`，失败是 `1`。

场景包采用相同的可移植原则：

```text
scene_outputs/<scene-name>/
└── final/
    ├── <scene-name>.usd
    ├── static_validation.json
    └── assets/             # 相对 USD 依赖
```

复制或发布时应提供完整 `final/` 目录，而不是只提供根场景 USD。

## 测试

快速测试不需要 CUDA、模型权重或 Isaac Sim：

```bash
python -m unittest discover -s tests/unit
git diff --check
```

GPU 集成测试和 Isaac Sim 回归测试位于 `tests/integration/` 和
`tests/simulation/`；它们不会在 GitHub 托管 CI 上运行。

## 已知限制

- 单图重建无法可靠恢复完全遮挡的几何。
- 单图语义审查无法证明被遮挡部分正确。
- 物理先验不能替代实测材质或惯性数据。
- 静态 USD 检查不能证明稳定接触、容纳性、可抓取性或任务成功；这些属于 Loop 2。
- SAM3/SAM3D 权重受上游访问条件和许可证约束。

## 贡献与安全

提交 Pull Request 前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。可复现 bug 和功能建议请
使用 issue 模板。安全或行为规范问题请按 [SECURITY.md](SECURITY.md) 与
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) 所述方式私下报告。

## 许可证与第三方软件

项目自行编写的源码、文档和样例输入采用 [Apache License 2.0](LICENSE)。SAM3、SAM 3D
Objects、Isaac Sim、模型权重和其他依赖仍受各自许可证与访问条款约束。详见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
