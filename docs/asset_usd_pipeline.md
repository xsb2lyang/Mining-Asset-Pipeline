# 资产 USD 化 / 物理化 试跑记录

> 配合 `docs/sam3_to_sam3d_pipeline.md`:本笔记衔接 SAM3D 输出(`mug.{glb,obj}`)→ USD → 物理化 → 静态校验。
> 跑通时间:2026-07-12

---

## 1. 测试目标

把 SAM3D 生成的"马克杯"几何(`outputs/sam3d_test/red_mug/mug.obj`)
转成带 PhysX 物理属性的 USD,使其在 Isaac Sim 5.1.0 中
可直接落桌 / 抓取 / 推撞 —— **矿业场景对资产物理质量(密度、碰撞近似、惯量)
要求很高**,所以每个参数都要按物体实际语义钉死。

---

## 2. 现有脚本清单(`asset_pipeline/isaac/`)

| 脚本 | 作用 | 关键参数 |
|---|---|---|
| `convert_glb_to_usd.py` | GLB/OBJ/FBX/STL → USD | `--input` `--output` `--single-mesh` `--ignore-materials` |
| `prepare_physics.py` | 加 RigidBodyAPI + MassAPI + CollisionAPI | `--collision {convexHull \| convexDecomposition \| sdf}` + `--mass` 或 `--density` |
| `validate_asset.py` | 静态 schema 校验(打印 JSON 到 stdout) | `--input` |
| `inspect_physics.py` **(本次新增)** | 同上,但 **写文件**(`--out`),绕开 Kit stdout 截取 | `--input` `--out` |
| `apply_physics_material.py` **(第三轮新增)** | 按物体语义增补物理材质、刚体、质量/惯量和接触参数 | `--input` `--output` + 按需 physics flags |

---

## 3. 物体语义识别

| 维度 | 取值 | 依据 |
|---|---|---|
| **类别** | 陶瓷马克杯 | 用户 prompt `"a red mug"` + RGB 视觉 |
| **几何尺度** | 包围盒 (-0.498, -0.398, -0.409) → (0.495, 0.397, 0.410) m,约 1×1×1 m | SAM3D 输出 + trimesh 校验 |
| **真实马克杯体积** | 0.30–0.40 L(350 mL 工业标准) | 日常参照 |
| **trimesh 报告体积** | 0.0357 m³(35.7 L)**—— bug 量级** | 网格含内壁 + 把手段,trimesh `volume` 把内部空腔算成实心 |
| **真实密度** | 陶瓷 2.3–2.8 g/cm³,取 **2.5 g/cm³** | 工程材料表 |
| **真实质量** | 空杯 0.35 L × 2500 ≈ **0.875 kg**,加满水 ~1.2 kg | 工业参考 300–500 g |

> ⚠️ **不直接用 `--mass`** —— 因为不知道真实体积(被 mesh bug 干扰);用 `--density` 让 PhysX 自己从 `density × mesh 体素`算 mass + principal inertia,语义更稳。

---

## 4. 物理参数决策表(为何这样选)

### 4.1 `convert_glb_to_usd.py`

```
python.sh convert_glb_to_usd.py \
    --input  outputs/sam3d_test/red_mug/mug.obj \
    --output outputs/sam3d_test/red_mug/mug.usd \
    --single-mesh
```

| 参数 | 取值 | 语义理由 |
|---|---|---|
| `--input mug.obj` | OBJ 而非 GLB | OBJ 文本格式,Isaac Asset Converter 解析最稳；**仅适用于不要求保留顶点色的几何/物理测试** |
| `--single-mesh` | True | SAM3D 输出含"外壁 + 内壁 + 把手"多个 mesh;合并成一个让 MassAPI 锚点单一清晰 |
| `--ignore-materials` | (默认 False) | 保留输入中存在的渲染材质；它不能恢复 OBJ 已经没有的颜色信息 |

> **颜色保真规则(第三轮补充):** 本次 `mug.obj` 没有 MTL/贴图/顶点色，转 USD 后会使用
> 默认灰色外观；`--ignore-materials=False` 不能凭空恢复红色。SAM3D 的 `mug.glb` 保留了
> 顶点色，因此需要保留原始 RGB 外观时应改用 `mug.glb` 作为 converter 输入。物理材质通过
> `material:binding:physics` 绑定，不会覆盖视觉材质或 `displayColor`。

**脚本 hardcode 的 converter 选项**(脚本内部固定,无 flag):

| 字段 | 值 | 效果 |
|---|---|---|
| `ignore_animation` | True | cup 没有动画 |
| `ignore_cameras` | True | cup 不是相机 |
| `smooth_normals` | True | 平滑法线 → 渲染好 |
| `use_meter_as_world_unit` | True | 1 单位 = 1 米(SAM3D bbox 正好 1×1×1 m,**幸运!**)|

### 4.2 `prepare_physics.py`

```
python.sh prepare_physics.py \
    --input  outputs/sam3d_test/red_mug/mug.usd \
    --output outputs/sam3d_test/red_mug/mug_physics.usd \
    --collision convexHull \
    --density 2500
```

| 参数 | 取值 | 语义理由 |
|---|---|---|
| `--collision convexHull` | **convexHull** | mug 整体接近凸,把手小凹 + 杯口凹。一个凸包就够了。`convexDecomposition` 会拆 8+ 个凸块,**落桌会反复弹跳、姿态不稳**;`convexHull` 物理稳定、接触少、落桌更"自然" |
| `--density 2500` | **2500 kg/m³** | 陶瓷马克杯真实密度;PhysX 自动算 mass + inertia;不写死 mass 让语义保真 |

### 4.3 不写的东西(脚本不支持 / 不适用)

| 项 | 状态 | 说明 |
|---|---|---|
| `UsdPhysics.MaterialAPI`(摩擦 / 弹性) | **缺失** | `prepare_physics.py` 没写,Isaac 默认 friction=0.5 / restitution=0,demo 可用;矿业场景**应补**(陶瓷:静摩擦 ~0.5 / 动摩擦 ~0.4 / restitution ~0.05) |
| 单位缩放 | 不需要 | SAM3D bbox 已经是 1×1×1 m,`use_meter_as_world_unit=True` 刚好对齐 |
| USD up axis | 不修改 | 默认 Y-up,与 Isaac Sim 一致 |

### 4.4 `validate_asset.py` 局限

- 它把结果 `print(json.dumps(...))` 到 stdout —— **Kit headless 模式截走 stdout**,实际看不到
- 解决:**新增 `inspect_physics.py`,把结果写到 `--out` 文件**,绕开 Kit 截取

---

## 5. 实际跑通结果

### 5.1 文件落地

```
outputs/sam3d_test/red_mug/
├── mug.glb            22.7 MB    SAM3D 网格(GLB)
├── mug.obj            46.0 MB    SAM3D 网格(OBJ)
├── mug.ply            44.8 MB    SAM3D 高斯溅射
├── mug.usd            9.3 MB     ← convert_glb_to_usd.py 产物
├── mug_physics.usd    9.3 MB     ← prepare_physics.py 产物(挂 RigidBodyAPI/CollisionAPI/MassAPI)
└── inspect.json       (schema 校验报告)
```

### 5.2 `inspect.json`(完整 schema 校验报告)

```json
{
  "input": ".../mug_physics.usd",
  "mesh_count": 1,
  "collider_count": 1,
  "rigid_body_count": 1,
  "mass_api_count": 1,
  "checks": {
    "has_mesh": true,
    "all_meshes_have_collision": true,
    "has_rigid_body": true,
    "has_mass_api": true
  },
  "rigid_bodies": ["/World"],
  "mass_apis": [
    {
      "prim": "/World",
      "mass_kg": 0.0,
      "density_kg_m3": 2500.0
    }
  ],
  "collision_approximation": {
    "/World/mug/mesh": "convexHull"
  },
  "status": "ok"
}
```

**全部 schema 检查通过 ✅**

### 5.3 解读

| 项 | 值 | 含义 |
|---|---|---|
| `mesh_count = 1` | `--single-mesh` 生效 | 单 mesh,MassAPI 锚点清晰 |
| `collider_count = 1` | 每个 mesh 都有 collision | convexHull 近似挂到 `/World/mug/mesh` |
| `rigid_body = /World` | root prim 挂 RigidBodyAPI | PhysX 把它当 dynamic body |
| `density = 2500 kg/m³` | 陶瓷 | PhysX 用 `density × 体素` 算真实 mass |
| `mass_kg = 0.0` | MassAPI 没显式赋 mass | 不影响仿真;PhysX 自动按密度算 |

---

## 6. 路上踩的 3 个真实坑

### 6.1 `python.sh` 与 conda 冲突

```
Warning: running in conda env, please deactivate before executing this script
```

**原因:** 当前 shell 在 conda base env;`python.sh` 检测到 conda 后拒绝跑(它要求纯净环境)。
**修法(在 sub-shell 里 unset conda 变量):**

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
bash /path/to/isaac-sim-5.1.0/python.sh ...
```

### 6.2 Kit headless 模式截走 stdout

`validate_asset.py` 的 `print(json.dumps(...))` 在 headless Kit 下看不到 —— Kit 把 Python sys.stdout 接管给 logger,**print 走到 Kit log 而非 tty stdout**。
**修法:** 新增 `inspect_physics.py` 把 JSON 写到 `--out` 文件,绕开 stdout。

### 6.3 `from pxr import Usd` 在 Isaac 自带 Python 里 ModuleNotFoundError

**原因:** `pxr` 不是普通 Python 包,Kit 通过 C++ runtime 在 `SimulationApp()` 启动时注册。
**修法:** 任何要 import `pxr` 的脚本必须先 `from isaacsim import SimulationApp; app = SimulationApp({"headless": True})` —— 哪怕只是用 `pxr` API 也要先 bootstrap。

---

## 7. 复跑命令

```bash
# 1) OBJ → USD(几何)
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
bash /home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0/python.sh \
  /home/user/Xsb_WS/Benchmark/Assest_maker/asset_pipeline/isaac/convert_glb_to_usd.py \
  --input  /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug.obj \
  --output /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug.usd \
  --single-mesh

# 2) 加物理(陶瓷密度 2500,凸包碰撞)
bash /home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0/python.sh \
  /home/user/Xsb_WS/Benchmark/Assest_maker/asset_pipeline/isaac/prepare_physics.py \
  --input     /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug.usd \
  --output    /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug_physics.usd \
  --collision convexHull \
  --density   2500

# 3) 静态 schema 校验(写到 inspect.json)
bash /home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0/python.sh \
  /home/user/Xsb_WS/Benchmark/Assest_maker/asset_pipeline/isaac/inspect_physics.py \
  --input /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug_physics.usd \
  --out   /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/inspect.json
```

---

## 8. 后续(本次没做)

- [x] ~~**补 MaterialAPI** —— ...~~
- [x] ~~**真实质量反算** —— ...~~
- [x] ~~**动态仿真回归测试** —— ...~~
- [x] ~~**矿业对象适配** —— ...~~

## 9. `convert_glb_to_usd.py` 扩展(2026-07-12 第二轮)

> 之前的脚本(我们项目内)只暴露 4 个 CLI flag,`AssetConverterContext` 的其他
> 内部选项都被写死。NVIDIA 官方的 `asset_usd_converter.py` 也只暴露 3 个 flag。
> 二者都没把隐藏选项开放到 CLI。

我们决定**保留项目脚本 + 把 AssetConverterContext 字段暴露**,理由:
- 项目脚本已有 single-file 工作流(`--input`/`--output`),比官方 batch 更适合
  当前一次性资产转换
- 矿业场景中不同物体需要不同 scale / smooth_normals / ignore_animation,
  把这些选项暴露给 CLI 才能差异化

### 9.1 暴露的新 flag

| 参数 | 默认 | 对应 AssetConverterContext 字段 | 语义 |
|---|---|---|---|
| `--ignore-materials` | False | `ignore_materials` | 不加载材质 |
| `--ignore-animation` | False | `ignore_animation` | 丢弃骨骼/关键帧 |
| `--ignore-cameras` | False | `ignore_cameras` | 丢弃嵌入相机 |
| `--single-mesh` | False | `single_mesh` | 合并所有 mesh |
| `--smooth-normals` | False | `smooth_normals` | 平滑法线 |
| `--preview-surface` | False | `preview_surface` | 简易预览 shader |
| `--support-point-instancer` | False | `support_point_instancer` | 保留点实例化 |
| `--embed-mdl-in-usd` | False | `embed_mdl_in_usd` | 把 MDL 嵌入 USD |
| `--create-world-as-default-root-prim` | False | `create_world_as_default_root_prim` | 包到 /World |
| `--no-meter-world-unit` | False | `use_meter_as_world_unit = False` | 不强制米制 |
| `--scale <float>` | None | (后处理 Xform scale op) | 整体缩放,矿业尺度不一 |

> ⚠️ 默认值与 NVIDIA 官方 `asset_usd_converter.py` 注释里的"推荐值"对齐。
> 改变某个默认 = 全项目行为变更,改前先知会。

### 9.2 `--scale` 实现方式

不在 AssetConverterContext 里调(scale 不在那个 API 里),
而是在 converter 返回后,**用 `UsdGeom.Xform` 包一层**,在 Xform 上
`AddScaleOp().Set(Gf.Vec3d(s, s, s))`。这是 USD 推荐的"后期缩放"方式,
不破坏原始 mesh。

### 9.3 验证

```
mug.obj  --(扩展版 convert_glb_to_usd.py --single-mesh)-->  mug_v2.usd  (9.3 MB)
mug_v2.usd  --(prepare_physics.py --collision convexHull --density 2500)-->  mug_v2_physics.usd
mug_v2_physics.usd  --(inspect_physics.py)-->  inspect_v2_physics.json  (status=ok, 与扩展前一致)
```

`mug_v2.usd` 与原 `mug.usd` 字节级一致 (9305346 = 9305346),证明默认值行为未变;
`mug_v2_physics.usd` 全部 4 项 schema 检查通过,扩展未破坏兼容性。

### 9.4 GLB 顶点色保真验证(2026-07-12 第三轮)

为修复 OBJ 路径导入 Isaac Sim 后显示灰色的问题，使用 GLB 重新生成独立产物：

```
mug.glb → mug_glb.usd → mug_glb_physics.usd → mug_glb_material.usd
```

- `mug_glb_material.usd` 为 **48 MB**；mesh `/world/geometry_0/geometry_0` 保留顶点
  `displayColor`，其中首批颜色为深红色范围；
- 物理材质仍以 `physics` purpose 单独绑定，静摩擦/动摩擦/弹性为 `0.5/0.4/0.05`；
- `inspect_glb_material.json` 的 mesh、collision、rigid body、MassAPI 四项检查均为 `ok`。

后续需要视觉保真时，使用 GLB 路径；仅需要网格和物理时，OBJ 路径仍可作为更紧凑的
调试输入。

---

- [x] **补 MaterialAPI** —— 新增 `apply_physics_material.py`，创建物理材质并直接绑定到每个 mesh：陶瓷示例为静摩擦 0.5、动摩擦 0.4、restitution 0.05
- [ ] **真实质量反算** —— 用 ray casting 测"水的体积"(杯口朝上时占据的体积)然后 `mass = density × water_volume`,比从 mesh 顶点数粗估更准
- [ ] **动态仿真回归测试** —— 写 `drop_test.py`:放桌上,自由落体,看能否稳定停下 + 接触点正确
- [ ] **矿业对象适配** —— 把 mug 换成矿卡 / 矿石堆 / 钻机,各自配密度(钢 7850、铁矿 5000、橡胶 1100)与碰撞近似
- [ ] **MaterialAPI 与 collision 联动** —— collision 改 `convexDecomposition` 时,MaterialAPI 仍要保持(摩擦对堆叠/抓取关键)

---

## 10. `apply_physics_material.py`：材质与刚体微调(2026-07-12 第三轮)

脚本位于 `asset_pipeline/isaac/apply_physics_material.py`。它直接调用 Isaac Sim 5.1
随附的 `UsdPhysics` / `PhysxSchema` schema，不依赖过时的高层 wrapper；所以写出的
USD 可在 Isaac Sim 的 Property 面板继续编辑。

范围是**单个刚体 mesh 资产**的全部已公开 schema 属性：
`MaterialAPI`、`PhysxMaterialAPI`、`RigidBodyAPI`、`PhysxRigidBodyAPI`、`MassAPI`、
`CollisionAPI`、`MeshCollisionAPI`、`PhysxCollisionAPI`。关节/Articulation、粒子、布料和
可变形体属于另一类资产，不能对 SAM3D 普通道具盲目套用，因此不在本脚本中创建。

### 10.1 材质参数

| CLI 参数 | USD/PhysX 字段 | 用途 |
|---|---|---|
| `--static-friction` / `--dynamic-friction` | `physics:staticFriction` / `physics:dynamicFriction` | 静摩擦与动摩擦，均须 ≥ 0 |
| `--restitution` | `physics:restitution` | 弹性/反弹，限定 0–1 |
| `--material-density` | `physics:density` (MaterialAPI) | 物理材质密度，单刚体时不要与下方 MassAPI 的质量/密度混用 |
| `--friction-combine-mode` | `physxMaterial:frictionCombineMode` | 两个接触材质摩擦如何合并：`average/min/multiply/max` |
| `--restitution-combine-mode` | `physxMaterial:restitutionCombineMode` | 两个接触材质弹性如何合并 |
| `--damping-combine-mode` | `physxMaterial:dampingCombineMode` | 柔顺接触阻尼如何合并 |
| `--compliant-contact-acceleration-spring` | `physxMaterial:compliantContactAccelerationSpring` | 柔顺接触的 acceleration-spring 开关 |
| `--compliant-contact-stiffness` / `--compliant-contact-damping` | `physxMaterial:compliantContactStiffness` / `...Damping` | 接触弹簧刚度/阻尼；刚度为 0 时保持普通刚性接触 |

脚本默认在 `<root>/Looks/PhysicsMaterial` 创建材质，并把 `materialPurpose="physics"`
的绑定直接写给每个 mesh；`--material-path`、`--bind-to`、`--binding-strength` 可覆盖。

### 10.2 刚体、质量与碰撞参数

| 类别 | 参数 |
|---|---|
| 基础刚体 | `--rigid-body-enabled`、`--kinematic-enabled`、`--starts-asleep`、`--linear-velocity X Y Z`、`--angular-velocity X Y Z` |
| PhysX 刚体稳定性 | `--linear-damping`、`--angular-damping`、`--max-linear-velocity`、`--max-angular-velocity`、`--sleep-threshold`、`--stabilization-threshold`、`--max-depenetration-velocity`、`--max-contact-impulse`、`--solver-position-iterations`、`--solver-velocity-iterations` |
| PhysX 刚体行为 | `--enable-ccd`、`--enable-speculative-ccd`、`--retain-accelerations`、`--enable-gyroscopic-forces`、`--disable-gravity`、`--solve-contact`、`--locked-pos-axis`、`--locked-rot-axis`、`--contact-slop-coefficient`、`--cfm-scale` |
| 质量/惯量 | `--mass` 或 `--mass-density`（二选一）、`--center-of-mass X Y Z`、`--diagonal-inertia IX IY IZ`、`--principal-axes W X Y Z` |
| 碰撞 | `--collision-enabled`、`--collision-approximation`、`--contact-offset`、`--rest-offset`、`--torsional-patch-radius`、`--min-torsional-patch-radius` |

`--collision-approximation` 支持 Isaac Sim 官方列出的
`none`、`convexDecomposition`、`convexHull`、`boundingSphere`、`boundingCube`、
`meshSimplification`、`sdf`、`sphereFill`。动态刚体通常优先 convex hull/decomposition；
三角网格和 mesh simplification 不适用于动态刚体，SDF 的细节更好但开销更大。

### 10.3 陶瓷马克杯复跑示例

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
bash /home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0/python.sh \
  /home/user/Xsb_WS/Benchmark/Assest_maker/asset_pipeline/isaac/apply_physics_material.py \
  --input  /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug_v2_physics.usd \
  --output /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug_v2_material.usd \
  --report /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/material_report.json \
  --static-friction 0.5 --dynamic-friction 0.4 --restitution 0.05 \
  --friction-combine-mode average --restitution-combine-mode max \
  --linear-damping 0.02 --angular-damping 0.05 --enable-ccd \
  --solver-position-iterations 16 --solver-velocity-iterations 2 \
  --contact-offset 0.01 --rest-offset 0.001
```

本次验证已读回 USD：材质绑定在 `/World/mug/mesh`，摩擦为 `0.5/0.4`、restitution
为 `0.05`，CCD 为 true，线性/角阻尼为 `0.02/0.05`，接触/静止偏移为 `0.01/0.001 m`。
`--report` 写 JSON 文件，避免 Kit headless 截走 stdout。

官方参考：[Isaac Sim Core API 的 physics material / collider 文档](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/py/source/extensions/isaacsim.core.api/docs/index.html)、[添加 Physics Material 教程](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/core_api_tutorials/tutorial_core_adding_props.html)。

## 11. 与 SAM3D pipeline 衔接

```
SAM3 → mask (outputs/sam3d_test/step1_sam3.npz)
  ↓
SAM3D → mesh {glb, obj, ply} (outputs/sam3d_test/red_mug/)
  ↓
convert_glb_to_usd.py → mug.usd
  ↓
prepare_physics.py → mug_physics.usd  ← 资产工作流第二步(物理化)
  ↓
apply_physics_material.py → mug_material.usd  ← 摩擦/弹性/阻尼/CCD/接触等细化
  ↓
inspect_physics.py → inspect.json   ← 静态校验
  ↓
[未做] Isaac Sim 动态回归测试 → "Simulation-ready" 标签
```

---

*文件创建于 2026-07-12。下次如要跑矿业资产(矿卡 / 钻机 / 矿石),参考本笔记"§3 物体语义"和"§4.2 参数决策表"的密度 / 碰撞近似对应关系。*
