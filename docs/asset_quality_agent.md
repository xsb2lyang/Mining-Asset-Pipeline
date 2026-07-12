# 资产质量保障 Agent（第一期）

本地 Agent 把现有的 SAM3、SAM3D 和 USD 工具包装成一个有人类门禁的资产生产流程：

```text
RGB + Prompt → 自动检查 → 人工视觉审查 → 物理配置确认 → USD / 基础物理化
```

动态落体、容器性、抓取和其他 Isaac Sim 任务验证属于后续 Loop 2，不在本期范围内。

## 启动

先按 [setup.md](setup.md) 配置 SAM3、SAM3D 和 Isaac Sim，并确保 `ISAAC_SIM_PATH` 已设置。网页在基础 Python 环境中运行，SAM3/SAM3D 仍由其各自的 Conda 环境执行：

```bash
python scripts/launch_asset_agent.py --output-root outputs
```

默认地址为 `http://127.0.0.1:7860`。若当前基础环境缺少网页依赖，可安装项目的 `ui` extra。

## 使用流程

1. 上传 RGB，输入 prompt；资产类别、任务和机器人约束可选。
2. Agent 创建唯一资产目录，运行 SAM3 与 SAM3D，并展示 mask、离屏渲染的静态 mesh 预览、GLB 和自动检查报告。静态预览是人工审查主视图；浏览器的交互式 GLB 预览受 WebGL 能力影响，仅作为补充。
3. 人工批准视觉资产；如拒绝，选择问题类别，并可提供修订 prompt、SAM3 候选编号或自由文本反馈。
4. Agent 只执行受控修复：重选/重跑 SAM3，或使用新 seed 重跑 SAM3D。无法安全修复的问题会保留为人工待处理状态。
5. 批准后，确认 Agent 提议的材质和碰撞 profile；随后自动生成视觉 USD、物理 USD 和静态检查报告。

## 每资产输出

每次任务唯一地写入 `outputs/<timestamp>-<slug>-<shortid>/`：

```text
manifest.json     # 可恢复的状态机、相对路径和事件历史
request.json      # 用户输入
input/            # 输入 RGB 的受控副本和哈希
visual/           # SAM3、SAM3D、自动检查与人工审查
physics/          # USD、确认的 profile、物理材质与静态检查
final/            # 通过静态检查的 asset.usd 与 asset_report.json
```

视觉结果被人工反馈替换时，旧版本才会移动到 `history/visual_XXX/`。所有 manifest 中的 artifact 路径都相对于资产根目录。

## 规则与限制

自动检查覆盖 mask 候选、置信度、mask 面积、box 合法性，以及 GLB 是否存在有效 mesh、顶点/面与颜色信息。每个阶段最多尝试三个有意义的变体；不会无限重试。

第一期默认使用规则策略，LLM 仅保留为将来的可插拔解释/建议接口。它不会自动补洞、编辑纹理或伪造几何修复；这类反馈会请求新的图像、prompt 或人工处理。
