# 资产质量保障 Agent（第一期）

本地 Agent 把 SAM3、SAM3D 和 USD 工具包装成无人值守的命令行资产生产流程：

```text
RGB + Prompt → 自动视觉检查 → Physics Author/Critic → USD / 基础物理化
```

当前版本不包含网页 UI。命令行在确定性视觉检查完成后记录自动批准并继续执行；如果任务要求人工签字，应在任务完成后检查 `visual/` 中的预览和报告。动态落体、容器性、抓取和其他 Isaac Sim 任务验证属于后续 Loop 2，不在本期范围内。

## 启动

先按 [setup.md](setup.md) 配置主控环境、SAM3、SAM3D 和 Isaac Sim，然后运行：

```bash
source .venv/bin/activate
source environments/local.env

python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

批量入口是 `scripts/batch_pipeline.py`，完整参数见 [cli_pipeline.md](cli_pipeline.md)。

## 使用流程

1. CLI 接收 RGB、prompt，以及可选的资产类别、目标任务和机器人约束。
2. Agent 创建唯一资产目录，运行 SAM3，检查候选、置信度、mask 面积和 box 合法性，并在可确定时自动选择更合适的候选。
3. Agent 运行 SAM3D，检查 GLB、mesh、顶点/面、边界和颜色信息；失败时最多尝试三个有意义的 seed。
4. CLI 记录视觉阶段自动批准。`visual/sam3/preview.png`、`visual/sam3d/preview.png` 和 JSON 报告保留供事后检查。
5. Physics Author 根据 prompt、类别和 YAML profile 写入 `physics/physics_spec.yaml`；Physics Critic 检查 schema、密度、摩擦/弹性、质量、阻尼和容器碰撞不变量。
6. 若 Critic 拒绝，Author 只执行可解释的机械修订，例如把开放容器的 `convexHull` 改为 `sdf`。最多三轮；未收敛则状态为 `blocked`，不会写入最终资产。
7. Critic 通过后，Agent 生成视觉 USD、物理 USD、基础仿真 USD 和静态检查报告；检查通过才写入 `final/asset.usd`。

## 每资产输出

每次任务唯一地写入 `outputs/<timestamp>-<slug>-<shortid>/`：

```text
manifest.json     # 可恢复的状态机、相对路径和事件历史
request.json      # 用户输入
input/            # 输入 RGB 的受控副本和哈希
visual/           # SAM3、SAM3D、自动检查与审批记录
physics/          # physics_spec.yaml、逐轮 Critic 记录、USD、物理材质与静态检查
final/            # 通过静态检查的 asset.usd 与 asset_report.json
```

视觉结果被修订输入替换时，旧版本才会移动到 `history/visual_XXX/`。所有 manifest 中的 artifact 路径都相对于资产根目录。

## 规则与限制

自动检查覆盖 mask 候选、置信度、mask 面积、box 合法性，以及 GLB 是否存在有效 mesh、顶点/面与颜色信息。每个阶段最多尝试三个有意义的变体；不会无限重试，也不会把自动批准解释为人工质量认证。

`configs/physics_spec_template.yaml` 定义了每资产物理规格的公开字段；当前工作流把材质、质量/密度、碰撞近似、摩擦、弹性、阻尼、CCD 和重力开关映射到现有 USD 脚本。`apply_physics_material.py` 的其余高级参数仍可由后续 policy 扩展填入。

第一期默认使用可复现的规则策略。CLI 可通过 `--use-llm-critic` 注入可选
Claude 物理 Critic；缺少 SDK、密钥或 API/解析失败时会带审计标记降级为规则
Critic。它不会自动补洞、编辑纹理或伪造几何修复；这类问题需要新的图像、
prompt 或离线人工处理。
