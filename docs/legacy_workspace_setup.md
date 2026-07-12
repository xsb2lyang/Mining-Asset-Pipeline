# Legacy 本地工作区部署说明

> 本文记录迁移前本地工作区的实际部署路径。新克隆仓库的可复现安装方式将由
> `environments/` 和 `third_party/` 提供；不要把模型权重或 Isaac Sim 安装目录提交到 Git。

目录：`/home/user/Xsb_WS/Benchmark/Assest_maker`

## 已部署代码

- `sam3/`：Meta SAM 3 图片/视频概念分割
- `sam-3d-objects/`：Meta SAM 3D Objects 单图物体/场景重建

## 环境

```bash
conda activate sam3
cd /home/user/Xsb_WS/Benchmark/Assest_maker
```

SAM 3 环境已安装 PyTorch 2.9.1 + CUDA 12.8，并使用 GPU 验证。

SAM 3D Objects 使用独立环境：

```bash
conda activate sam3d-objects
cd /home/user/Xsb_WS/Benchmark/Assest_maker
```

## 模型权重

Meta 权重需要在 Hugging Face 对应模型页面申请访问权限，并完成登录：

```bash
hf auth login
```

SAM 3 权重下载示例：

```bash
conda activate sam3
hf download facebook/sam3 --local-dir checkpoints/sam3
```

SAM 3D Objects 权重下载示例：

```bash
conda activate sam3d-objects
cd sam-3d-objects
hf download --repo-type model --local-dir checkpoints/hf-download --max-workers 1 facebook/sam-3d-objects
mv checkpoints/hf-download/checkpoints checkpoints/hf
rm -rf checkpoints/hf-download
```

权重尚未自动下载，因为 Hugging Face 访问授权和登录令牌属于用户账户权限。

## 端到端测试记录

`outputs/sam3d_test/` 目录里包含一次完整跑通的 **RGB → OBJ/GLB** 小 pipeline 输出:

- 当前入口脚本: `scripts/run_sam3.py`(`sam3` 环境)
- 当前出口脚本: `scripts/run_sam3d.py`(`sam3d-objects` 环境)
- 产物: `outputs/sam3d_test/red_mug/mug.{ply,glb,obj}`

详细跑通记录、环境差异、bf16 / socks 代理 / MeshExtractResult 等坑的修法见:

**[`../../docs/sam3_to_sam3d_pipeline.md`](../../docs/sam3_to_sam3d_pipeline.md)**
