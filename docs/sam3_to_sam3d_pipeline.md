# SAM3 + SAM3D Objects 小 Pipeline 试跑记录

> 跑通情况:**自检 SAM3 → SAM3D Objects 端到端小 pipeline**,产出 OBJ / GLB / PLY 三份 3D 文件
> 记录人:Claude(模型 `claude-opus-4-8`)
> 跑通时间:2026-07-12
> 适用项目:`Benchmark/Assest_maker`(矿业资产自动化生产链路的早期原型)

> **仓库迁移说明:** 此记录保留当时的输出路径和产物名；可执行入口已迁至
> `scripts/run_sam3.py` 与 `scripts/run_sam3d.py`，不再放在 `outputs/` 中。

---

## 1. 目标与背景

> 项目定义(摘自用户粘贴的 pipeline 图):
>
> ```
> 任务描述 + RGB
>      ↓
>  生成候选 mask(SAM3)
>      ↓
> ┌── Loop 1:生成循环 ──┐
> │                      │
> │ SAM3D 生成候选       │
> │      ↓               │
> │ 几何/视觉/结构检测   │
> │      ↓               │
> │ mask/crop/seed 纠错  │
> └────────┬─────────────┘
>          ↓
>        最优 GLB
>          ↓
> ┌── Loop 2:物理循环 ───┐
> │                        │
> │ USD 转换与物理化       │
> │      ↓                 │
> │ Isaac Sim 测试         │
> │      ↓                 │
> │ 碰撞/质量/惯量自主修复 │
> └────────┬───────────────┘
>          ↓
>  Simulation-ready mining asset
> ```
>
> 本次仅做了最简版 **"RGB → OBJ / GLB"**(Loop 1 的最小可运行切片),未涉及 Loop 1 的检测器、纠错、Loop 2 与 Isaac Sim 物理仿真。

---

## 2. 环境与硬件

| 项 | 值 |
|---|---|
| 操作系统 | Linux 6.8 (Ubuntu 派生) |
| GPU | NVIDIA RTX 4090 ×2(capability 8.9,Ada) |
| CUDA Toolkit | 12.9 |
| Driver | 13.0 |
| Python | 3.11 |
| PyTorch | 2.9.1 + CUDA 12.8 |
| SAM3 conda env | `sam3`(已 `pip install -e .`) |
| SAM3D Objects conda env | `sam3d-objects`(`sam3d_objects` 包**未** `pip install`,源代直跑) |
| 关键依赖 | `trimesh`, `huggingface_hub`, `pytorch3d`, `warp`, `kaolin`, `gradio`(仅副作用) |
| 网络 | 设置了 `socks://127.0.0.1:7897/` 系统代理;外网可达 |

---

## 3. 测试输入

### 3.1 RGB 图

- **来源**:Unsplash 公共直链
- **图 ID**:`FOV3qVe_ooY`(被官方描述为 "a red mug on a table")
- **直链**:`https://images.unsplash.com/photo-1662560099838-9b229803fd7f?w=1200&q=80`(免登录)
- **本地**:`Benchmark/Assest_maker/outputs/sam3d_test/images/red_mug.jpg`
- **规格**:1200 × 1183 px,JPEG,155 KB,真实 RGB
- **画面内容**:中心一张陶瓷马克杯,放置在木桌上,顶部有热气冒出
- **拍摄角度**:杯子从杯口往下被裁切(顶部信息缺失,底部嵌入木桌),不是俯视全景

**为什么选这一张:**

| 候选 | 取舍 |
|---|---|
| 8 张候选里 3 张有 Unsplash+ 权限墙 | 不要 |
| 木桌背景("brown wooden table")和绿色背景 | 杯子主体与背景反差够大,SAM3 prompt 容易锁住 |
| 没有白底(cutout)图 | 但其实反而更接近真实矿业场景图 |

### 3.2 SAM3 文本 Prompt

```text
"a red mug"
```

挑这个 prompt 的考虑:

- **单主体 + 日常物** —— 对 SAM3 来说简单到不应该出错,作为 baseline
- **包含颜色属性** —— 验证 SAM3 对颜色细分的处理是否合理
- **矿业场景不重要** —— 本次只想验 pipeline 可跑通,不挑剔类别

---

## 4. 落地目录与产物

```
Benchmark/Assest_maker/outputs/sam3d_test/  # 历史测试输出（Git 忽略）
├── images/
│   └── red_mug.jpg                      # 输入 RGB
├── step1_sam3.npz                       # mask / boxes / scores / prompt
├── step1_preview.png                    # RGB + 绿色 mask 叠加
├── step1_meta.json                      # 含 score=0.978
└── red_mug/
    ├── mug.ply        44.8 MB           # 3D Gaussian Splat
    ├── mug.glb        22.7 MB           # 真 mesh(GLB)
    ├── mug.obj        46.1 MB           # 真 mesh(OBJ,与 GLB 同几何)
    └── summary.json                     # 输出键 / 路径 / mesh_used_source
```

| 产物体积比 | 含义 |
|---|---|
| `mug.ply` ≈ 44.8 MB | 三维高斯点的位置 + 球谐 + 不透明度等参数,膨胀大 |
| `mug.glb` ≈ 22.7 MB | 三角网格 + 顶点色,1.13M 面,**is_watertight=True** |
| `mug.obj` ≈ 46.1 MB | 同样的三角网格以文本格式存,体积大很多(无压缩) |

**几何信息**(trimesh 校验):

```
mug.obj : vertices=566790  faces=1134560
         bbox=(-0.498,-0.398,-0.409, 0.495,0.397,0.410)
         volume=0.0357      is_watertight=True
mug.glb : vertices=566790  faces=1134560
         bbox=(-0.498,-0.409,-0.397, 0.495,0.410,0.398)
         volume=0.0357      is_watertight=True
```

—— 1×1 包围盒里占了约 1/28 体积,形态是小尺寸杯状物。

---

## 5. 代码逻辑

### 5.1 总体流程

```
[Unsplash 直链]
   curl ---> images/red_mug.jpg

[sam3 环境] python scripts/run_sam3.py
   ├── build_sam3_image_model(checkpoint_path=.../sam3.pt, load_from_HF=False)
   ├── model.to(torch.float32)            # 留 fp32,绕过 dtype mismatch
   ├── monkey-patch sam3.perflib.fused.addmm_act    # 替换 fused kernel
   └── processor.set_image + set_text_prompt('a red mug')
       → step1_sam3.npz

[sam3d-objects 环境] python scripts/run_sam3d.py
   ├── 把 ALL_PROXY=socks://... 改写成 http://...      # 修 httpx 报错
   ├── Inference(checkpoints/hf/pipeline.yaml)
   ├── inference(rgb, mask, seed=42)
   ├── output['glb'] (trimesh.Scene) ─→ mug.glb
   ├── output['mesh'] (list[MeshExtractResult]) ─→ trimesh.Trimesh ─→ mug.obj
   └── output['gs'] (Gaussian) ──save_ply───→ mug.ply
```

### 5.2 关键设计

| 决策 | 原因 |
|---|---|
| 两个环境分开跑 | [`legacy_workspace_setup.md`](legacy_workspace_setup.md) 记录 SAM3 在 `sam3`、SAM3D 在 `sam3d-objects`;两者 PyTorch 与 CUDA 版本不同 |
| 不用 `load_from_HF=True` | 仓库已下好 `sam3.pt`(3.3 GB),免授权 |
| SAM3D 用源代直跑 | 仓库 `sam3d_objects` 包没有 `pip install`,直接 `sys.path.append("notebook")` |
| 强转 fp32 + 替换 fused kernel | 修复 bf16 / fp32 dtype 不匹配(详见第 6 节) |
| 多退路导出 mesh | 优先 `output['glb']`;失败转 `output['mesh']`;再失败 `ply → obj` 退路 |

---

## 6. 路上踩到的 5 个真实坑 + 修法

> 这一节是这份笔记最有信息量的部分,避免后人重复踩。

### 6.1 SAM3 在 Ada GPU 上 dtype mismatch(关键)

**现象:**

```
RuntimeError: mat1 and mat2 must have the same dtype, but got BFloat16 and Float
   at vitdet.py:71:  x = addmm_act(type(self.act), self.fc1, x)
   at vitdet.py:74:  x = self.fc2(x)            <- 这里第二次炸
   at decoder.py:77: self.linear1(tgt)          <- 另一处同样症状
```

**根因(双发):**

1. **`sam3/perflib/fused.py:addmm_act`** 内部无条件 `bias.to(bf16) / mat1.to(bf16) / mat2.to(bf16)`,输出必是 bf16。
2. **`sam3/model/decoder.py:79 forward_ffn`** 内置 `with torch.amp.autocast(device_type="cuda", enabled=False):` 强制 fp32。

> 一个把 mlp 输出强制成 bf16,另一个把 mlp 输入强制 fp32——必炸。

**修复:**

```python
# vitdet
def _safe_addmm_act(activation, linear, mat1):
    out = F.linear(mat1, linear.weight, linear.bias)   # 让 dtype 由 weight 决定
    if activation in (F.gelu, nn.GELU): out = F.gelu(out)
    if activation in (F.relu, nn.ReLU): out = F.relu(out)
    return out

sys.modules["sam3.perflib.fused"].addmm_act = _safe_addmm_act
import sam3.model.vitdet as _vitdet_mod
_vitdet_mod.addmm_act = _safe_addmm_act  # 因为 vitdet.py 在 import 时就锁定了符号

# 整模型保持 fp32 即可(无需 autocast / 不需要把每层改 bf16)
```

**为什么不直接 `model.to(torch.bfloat16)`:**

- autocast 不转换 internal cast 或被 `__init__` 重新 rebuild 的子模块 → 仍有漏网的 fp32 浮出
- 要全面覆盖需要递归走 `model.modules()`,但 `decoder.forward_ffn` 内的 `autocast(False)` 会再把 Linear 拉回 fp32
- 把 `addmm_act` 的 hard-cast 摘掉是最干净的单点修复

**佐证:** GitHub 官方 issue #8 / #13 / #4 都报同一个错,但建议的解法在这次环境上不够稳健。

### 6.2 `np.asarray(cuda_tensor)` 失败

```python
boxes_np = np.asarray(boxes)   # TypeError: can't convert cuda:0 tensor to numpy
```

**修:** 先 `.cpu().numpy()`,通用做法:

```python
masks_np = masks.cpu().numpy() if hasattr(masks, "cpu") else np.asarray(masks)
```

### 6.3 `sam3d_objects` 包未安装也能跑

`sam3d_objects/__init__.py` 中 `import sam3d_objects.init`,但仓库**根本没有** `init.py`(`__init__.py` 透传 `LIDRA_SKIP_INIT` 环境变量来跳过它)。

**原始 `notebook/inference.py` 已经做了:**

```python
import os
os.environ["CUDA_HOME"] = os.environ["CONDA_PREFIX"]
os.environ["LIDRA_SKIP_INIT"] = "true"
sys.path.append("notebook")
```

照抄即可,不必 `pip install -e .`。

### 6.4 gradio 链式触发 httpx → socks 代理解析失败

**现象:**

```
gradio → httpx → "Unknown scheme for proxy URL URL('socks://127.0.0.1:7897/')"
```

**原因:** `inference.py` 顶部 `import gradio as gr`,gradio 在 `__init__.py` 内构造一个 `httpx.Client()` 用于子进程通信,这个 client 立刻尝试解析 `ALL_PROXY=socks://...`,而 httpx 不支持 socks 直接 scheme(需要 `socks5://` 或 PySocks)。

**修法(脚本最开头加,先于一切 import):**

```python
for _k in ("ALL_PROXY", "all_proxy"):
    _v = os.environ.get(_k, "")
    if _v.startswith("socks://"):
        os.environ[_k] = "http://" + _v[len("socks://"):]
```

(我们不需要走 socks,只是绕开 httpx 的 url-parse。SAM3D 推理全程不联网。)

### 6.5 `output["mesh"]` 不是 trimesh

**实际形态:**

```python
out["mesh"] = [<sam3d_objects.model.backbone.tdfy_dit.representations.mesh.cube2mesh.MeshExtractResult object at 0x...>]
```

内部 dataclass:

```python
class MeshExtractResult:
    def __init__(self, vertices, faces, vertex_attrs=None, res=64):
        self.vertices = vertices            # torch.Tensor
        self.faces = faces.long()           # torch.Tensor
        self.vertex_attrs = vertex_attrs
        ...
```

**修法:** 转换为 `trimesh.Trimesh`:

```python
import trimesh
v = m.vertices.detach().cpu().numpy() if hasattr(m.vertices, "detach") else np.asarray(m.vertices)
f = m.faces.detach().cpu().numpy()    if hasattr(m.faces,    "detach") else np.asarray(m.faces)
mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
```

`output["glb"]` 直接就是 `trimesh.Scene`,`.export()` 可用 —— 优先用它,失败再走 `output["mesh"]`。

---

## 7. 结果回顾

| 维度 | 结果 |
|---|---|
| SAM3 mask | 21.5% 像素、score **0.978**,覆盖到杯身+手柄 |
| SAM3 bbox | `[277.06, 264.54, 973.36, 942.35]` —— 中心位置大概匹配 |
| SAM3D 端到端时间 | ~17 秒(RTX 4090,默认 precision) |
| 几何质量 | 566k 顶点 / 1.13M 面,**water-tight** |
| 体量 | 包围盒 1×1×1,体积 0.0357 —— 杯子尺度 |

> **失败/局限项:**
>
> 1. **杯子顶部被裁掉** — 输入图上沿就切掉了杯口,SAM3D 在顶部只能"猜"出近似的杯口,顶部封闭性可能略弱
> 2. **手柄粘连木桌背景** — 输入图背景就是木桌,SAM3 用 "a red mug" 大概率没把左边的曲柄全部纳入 mask,可能有部分手柄被背景"切掉"
> 3. **该图不是矿业场景的合适测试集** — 真要测矿卡 / 矿石堆 / 钻机,需要换图;但 SAM3 + SAM3D 这条链路本身已确认可跑

---

## 8. 后续计划(填表占位,不在本次范围)

> 来自 README/pipeline 图但**本次未做**的事项

- [ ] Loop 1 检测器:对生成的 OBJ 做几何检查(自交 / 长面 / 退化三角面)
- [ ] Loop 1 自纠:mask 重切 / crop 调整 / seed 重试 三个回退路径
- [ ] Loop 1 视觉一致:多角度渲染后回比 RGB
- [ ] Loop 2 USD 化 + `convert_glb_to_usd.py` 验证
- [ ] Loop 2 物理仿真回归测试(drop / push / grasp / stack 四类)
- [ ] Loop 2 自修复:碰撞近似、质量、惯量、摩擦系数的自动调整
- [ ] `agent_skill/` 串联两个 loop(LLM 决定哪一步需回退)
- [ ] 接 Isaac Sim 5.1.0,导入 USD 并物理仿真

---

## 9. 复跑命令清单

**Step 1 — SAM3(环境 `sam3`)**

```bash
source environments/local.env
conda run -n sam3 python scripts/run_sam3.py \
  --image "$PIPELINE_OUTPUT_DIR/sam3d_test/images/red_mug.jpg" \
  --prompt "a red mug" \
  --out-dir "$PIPELINE_OUTPUT_DIR/red_mug/sam3"
```

**Step 2 — SAM3D(环境 `sam3d-objects`)**

```bash
source environments/local.env
conda run -n sam3d-objects python scripts/run_sam3d.py \
  --image "$PIPELINE_OUTPUT_DIR/sam3d_test/images/red_mug.jpg" \
  --mask-npz "$PIPELINE_OUTPUT_DIR/red_mug/sam3/mask.npz" \
  --out-dir "$PIPELINE_OUTPUT_DIR/red_mug/sam3d"
```

> 注意:不要把两个 step 合在同一个 `conda run`(环境不同)。

---

## 10. 引用清单

| 来源 | 用途 |
|---|---|
| [`docs/legacy_workspace_setup.md`](legacy_workspace_setup.md) | 确认双环境、HF 权限与权重下载方式 |
| `Benchmark/Assest_maker/sam3/README.md` | SAM3 文本/视觉 prompt API 范式 |
| `Benchmark/Assest_maker/sam-3d-objects/README.md` | SAM3D inference 接口、output 键含义 |
| `Benchmark/Assest_maker/sam3/sam3/perflib/fused.py` | 找到 bf16 hard-cast 的源头 |
| `Benchmark/Assest_maker/sam3/sam3/model/decoder.py:79` | 找到 fp32 autocast(False) 源头 |
| GitHub SAM3 Issue #8 / #13 / #4 | 提供 bf16 修复思路的初始线索 |
| Unsplash 直链 `photo-1662560099838-9b229803fd7f` | 测试图 |

---

*文件创建于 2026-07-12,作者 Claude `claude-opus-4-8`(配合 Claude Code CLI)。后续如更新本文件,请保留 §6 "踩坑" 一节 —— 这是下次复现时最先读的部分。*
