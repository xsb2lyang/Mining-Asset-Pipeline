# USD 物理材质与刚体参数说明

`Benchmark/Assest_maker/asset_pipeline/isaac/apply_physics_material.py`
用于在已有 USD 资产上继续补充或调整 Isaac Sim 的物理属性。

它面向由 SAM3D 网格转换而来的**单刚体资产**，例如矿石、工具、容器、独立零件。
脚本不会修改原始输入文件；必须通过 `--output` 写出新的 USD。

```text
OBJ / GLB
  → convert_glb_to_usd.py
  → prepare_physics.py       # 刚体、质量/密度、碰撞近似
  → apply_physics_material.py # 摩擦、弹性、阻尼、CCD、接触等细化
```

## 1. 运行方式

`pxr` 与 PhysX schema 需要由 Isaac Sim bootstrap，因此使用 Isaac Sim 自带的
`python.sh` 执行：

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
bash /home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0/python.sh \
  /home/user/Xsb_WS/Benchmark/Assest_maker/asset_pipeline/isaac/apply_physics_material.py \
  --input  INPUT.usd \
  --output OUTPUT.usd \
  --report OUTPUT.report.json \
  [按物体语义选择参数]
```

可执行以下命令查看全部 CLI 参数：

```bash
bash /home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0/python.sh \
  /home/user/Xsb_WS/Benchmark/Assest_maker/asset_pipeline/isaac/apply_physics_material.py \
  --help
```

未传入的参数不会改写输入 USD 中已有的值。

## 2. 脚本会处理哪些官方 schema

| Schema | 用途 |
|---|---|
| `UsdPhysics.MaterialAPI` | 静/动摩擦、弹性、物理材质密度 |
| `PhysxSchema.PhysxMaterialAPI` | 材质合并规则、柔顺接触参数 |
| `UsdPhysics.RigidBodyAPI` | 刚体开关、运动学、初速度、初始休眠 |
| `PhysxSchema.PhysxRigidBodyAPI` | 阻尼、CCD、重力、接触求解器和稳定性参数 |
| `UsdPhysics.MassAPI` | 质量、密度、质心、惯量 |
| `UsdPhysics.CollisionAPI` / `MeshCollisionAPI` | 碰撞开关、碰撞近似 |
| `PhysxSchema.PhysxCollisionAPI` | 接触偏移与扭转摩擦接触参数 |

关节、Articulation、布料、粒子和可变形体属于不同的资产类型，本脚本不会为普通
SAM3D 网格自动创建这些 API。

## 3. 参数选择指南

### 3.1 物理材质

| 参数 | 含义 |
|---|---|
| `--static-friction` | 起滑前的摩擦系数，必须 ≥ 0 |
| `--dynamic-friction` | 发生相对滑动后的摩擦系数，必须 ≥ 0 |
| `--restitution` | 碰撞弹性，范围 0–1；0 表示无反弹 |
| `--material-density` | 材质密度，单位 kg/m³ |
| `--friction-combine-mode` | 两个材质接触时摩擦值的合并方式：`average/min/multiply/max` |
| `--restitution-combine-mode` | 两个材质接触时弹性值的合并方式 |
| `--damping-combine-mode` | 柔顺接触阻尼的合并方式 |
| `--compliant-contact-stiffness` | 柔顺接触弹簧刚度；0 保持普通刚性接触 |
| `--compliant-contact-damping` | 柔顺接触阻尼 |
| `--compliant-contact-acceleration-spring` | 使用 acceleration-spring 模式 |

对于一个独立刚体，`--material-density` 不要与 `--mass` 或 `--mass-density`
同时使用，以避免质量来源不明确。通常保留 `prepare_physics.py` 写入的
`--mass-density` 即可。

### 3.2 刚体与稳定性

| 参数组 | 参数 |
|---|---|
| 基本状态 | `--rigid-body-enabled`、`--kinematic-enabled`、`--starts-asleep` |
| 初始运动 | `--linear-velocity X Y Z`、`--angular-velocity X Y Z` |
| 阻尼与限速 | `--linear-damping`、`--angular-damping`、`--max-linear-velocity`、`--max-angular-velocity` |
| 稳定性 | `--sleep-threshold`、`--stabilization-threshold`、`--max-depenetration-velocity`、`--max-contact-impulse` |
| 求解器 | `--solver-position-iterations`、`--solver-velocity-iterations` |
| 特殊行为 | `--enable-ccd`、`--enable-speculative-ccd`、`--disable-gravity`、`--enable-gyroscopic-forces`、`--retain-accelerations`、`--solve-contact` |
| 自由度约束 | `--locked-pos-axis`、`--locked-rot-axis`；位掩码 X=1、Y=2、Z=4 |

高速、小尺寸或薄壁物体可能穿透碰撞体，可尝试 `--enable-ccd`。不要在未进行动态回归
测试前随意调高求解迭代或接触偏移。

### 3.3 质量、惯量与碰撞

| 参数 | 含义 |
|---|---|
| `--mass` | 显式质量，单位 kg |
| `--mass-density` | MassAPI 密度，单位 kg/m³；PhysX 据此推导质量/惯量 |
| `--center-of-mass X Y Z` | 局部质心，单位 m |
| `--diagonal-inertia IX IY IZ` | 主惯量，单位 kg·m² |
| `--principal-axes W X Y Z` | 惯量坐标系四元数 |
| `--collision-enabled` | 启用或禁用网格碰撞 |
| `--collision-approximation` | `none`、`convexDecomposition`、`convexHull`、`boundingSphere`、`boundingCube`、`meshSimplification`、`sdf`、`sphereFill` |
| `--contact-offset` / `--rest-offset` | 接触生成距离与静止分离距离，必须满足 contact offset > rest offset |
| `--torsional-patch-radius` / `--min-torsional-patch-radius` | 扭转摩擦接触半径 |

动态刚体通常选 `convexHull` 或 `convexDecomposition`。复杂凹形物体可以尝试
`sdf`，但碰撞计算成本更高；`none` 与 `meshSimplification` 对动态刚体会退化，
不应作为常规选择。

## 4. 示例：陶瓷马克杯

```bash
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
bash /home/user/Xsb_WS/Benchmark/simulator/isaac-sim-5.1.0/python.sh \
  /home/user/Xsb_WS/Benchmark/Assest_maker/asset_pipeline/isaac/apply_physics_material.py \
  --input  /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug_v2_physics.usd \
  --output /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/mug_v2_material.usd \
  --report /home/user/Xsb_WS/Benchmark/Assest_maker/outputs/sam3d_test/red_mug/material_report.json \
  --static-friction 0.5 \
  --dynamic-friction 0.4 \
  --restitution 0.05 \
  --friction-combine-mode average \
  --restitution-combine-mode max \
  --linear-damping 0.02 \
  --angular-damping 0.05 \
  --enable-ccd \
  --solver-position-iterations 16 \
  --solver-velocity-iterations 2 \
  --contact-offset 0.01 \
  --rest-offset 0.001
```

该命令创建 `/World/Looks/PhysicsMaterial`，并将它以 `physics` purpose 直接绑定到
资产的每个 mesh，不影响原本的渲染材质。`--report` 会写出修改过哪些属性，避免
Isaac Kit headless 模式截走 stdout。

## 5. 推荐工作方式

1. 用物体类别、材料、尺度和用途确定初始物理先验。
2. 先用 `prepare_physics.py` 写入碰撞近似与质量/密度。
3. 用本脚本补充摩擦、弹性、阻尼、CCD 等行为参数。
4. 用 `inspect_physics.py` 做 schema 静态检查。
5. 最后执行 drop / push / grasp / stack 等动态回归测试，根据结果再调整。

官方参考：

- [Isaac Sim 5.1 Core API：Physics Material 与 Collider](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/py/source/extensions/isaacsim.core.api/docs/index.html)
- [Isaac Sim 5.1：Adding Props / Physics Material](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/core_api_tutorials/tutorial_core_adding_props.html)
