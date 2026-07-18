# 资产质量保障 Agent（Loop 1）

当前实现把固定 Pipeline 升级为共享受控工具的 Agent：

```text
RGB + 粗 Prompt
→ 语义简报与 Prompt 规范化
→ SAM3 候选审查/受控切换
→ SAM3D 四视图审查/受控 seed 重试
→ Physics Author / Critic 隔离审查
→ 确定性规则最终否决
→ USD 物理化与静态一致性检查
→ final/asset.usd
```

没有网页 UI 和人工视觉审批。Loop 2 的动态落体、容器性、抓取与机器人任务测试尚未实现。

## 两种控制方式

### 仓库 Skill

在 Codex 或 Claude Code 中提供图片路径和粗 prompt，调用 `generate-mining-asset` Skill。Skill 使用当前会话模型做语义决策，只调用 `scripts/asset_tool.py` 白名单动作，不读取 `ANTHROPIC_API_KEY`，也不调用项目内 Claude API。

### 内置 Claude API Agent

```bash
export ANTHROPIC_API_KEY='仅保存在当前 shell'
python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "矿里用的纸筒"
```

内置 Agent 默认最多调用 8 次：Input Analyst 1 次、Visual Critic 3 次、Physics Author 2 次、Physics Critic 2 次。无 key、无 SDK 或 API 失败时进入确定性 fallback。

## 状态与输出

manifest v3 将总体状态、当前阶段和质量分开：

- `status`: `created | running | complete | blocked | failed`
- `phase`: 从 `input_analysis` 到 `finalization` 的九个阶段
- `quality`: `pending | agent_reviewed | degraded`

每次 SAM3 prompt 和 SAM3D seed 都保存在独立 attempt 目录中；成功步骤按相同 prompt/seed 重调时直接复用。`--resume <asset-id>` 从最后持久化阶段继续，schema v2 及更旧任务只读。

完整目录和 CLI 参数见 [cli_pipeline.md](cli_pipeline.md)。

## 审查边界

- Visual Critic 对比原图、所有 mask 候选拼图和 front/right/top/isometric 四视图。
- Physics Author 只负责生成 spec；Physics Critic 只读取落盘 spec、语义简报和报告。确定性 Critic 始终拥有最终否决权。
- 开放容器不能用会封口的 `convexHull`；细长/高速物体建议 CCD；可移动物体默认受重力。
- 密度、摩擦、弹性和阻尼是带来源说明的工程先验，不是实测值。
- fallback 只有同时命中专用材质和专用碰撞 profile、视觉结构检查与静态 USD 检查均通过时，才可输出 `quality=degraded`；generic fallback 必须 `blocked`。

`complete` 只表示 Loop 1 静态物理资产完成，不表示已经通过动态仿真或机器人任务认证。
