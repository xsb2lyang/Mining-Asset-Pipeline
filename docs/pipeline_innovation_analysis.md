# Mining Asset Pipeline 创新方向分析

> 面向矿业机器人 Benchmark 的任务条件化、反例驱动资产生成与认证
>
> 整理日期：2026-07-29

## 1. 核心结论

现有表述：

> 生成—仿真双闭环的 Agent 资产生产机制，将视觉三维生成与仿真物理化分离，
> 并依据结构化检查结果将错误路由至对应的修复阶段，从而在不修改底层三维生成
> 模型的情况下，规模化构建矿业仿真资产。

适合作为系统概述，但还不足以单独构成方法创新。更有潜力且更加严谨的研究主线是：

> **任务条件化的仿真实验设计 → 结构化反例 → 根因诊断 → 最小阶段修复
> → 证据化资产认证。**

研究故事应从“Agent 串联若干生成工具”提升为：

> **Agent 提出物理假设、设计诊断实验，并根据仿真反例修复资产。**

建议将最终方法概括为：

> 面向矿业机器人任务的任务条件化、反例驱动 Agentic 资产合成与认证框架。

---

## 2. 对现有 Pipeline 的严格判断

### 2.1 当前还不能严格称为“生成—仿真双闭环”

目前仓库中的 Loop 1 已经实现：

- SAM3 prompt 和 mask candidate 重试；
- SAM3D seed 重试；
- VLM 视觉审查；
- Physics Author/Critic；
- 确定性规则否决；
- USD schema 和 authored-value 静态检查；
- manifest、产物哈希、恢复和审计。

但当前流程尚未回答以下动态问题：

- 容器实际能否装载物体；
- 细长物体是否会发生高速穿透；
- 物体受到已知推力后的运动是否合理；
- 碰撞体是否与视觉几何一致；
- 机器人是否能够抓取、插入或搬运资产；
- 动态仿真失败后，应该修改几何、碰撞体还是物理参数。

当前
[`PhysicsCriticAgent`](../src/mining_asset_pipeline/agent/physics_agents.py)
主要检查摩擦、密度、碰撞模式、CCD、重力等参数和规则是否合法；
[`AgentTools.author_usd`](../src/mining_asset_pipeline/agent/tools.py)
及静态检查主要证明“USD 中实际写入的值与 physics spec 一致”。

因此，当前流程更准确的描述是：

> 视觉生成闭环 + 静态物理 authoring。

真正的动态 Loop 2 尚待在
[`tests/simulation/`](../tests/simulation/README.md)
中实现。

### 2.2 当前错误路由仍属于有限重试和规则修正

现有视觉修复动作主要包括：

```text
rewrite prompt
select mask candidate
rerun SAM3D with another seed
block
```

物理修复主要包括：

```text
collision approximation
friction / restitution
density
gravity
CCD
damping
```

这已经构成良好的工程基础，但还没有形成严格意义上的诊断性路由：

- 为什么是 collider 错，而不是 visual geometry 错？
- 为什么应该修改 friction，而不是 mass？
- 为什么应该局部修复，而不是重新运行 SAM3D？
- 如何证明选择的是最低成本的修复路径？
- 修复后是否破坏了此前已经通过的性质？

这些问题可以进一步发展为可验证的方法贡献。

### 2.3 “规模化”和“model-agnostic”必须由实验支持

如果论文声称 model-agnostic，至少应在两个三维生成 backbone 上验证。只使用 SAM3D
无法证明方法对底层生成器具有普适性。

如果声称规模化，需要至少报告：

- 总资产数量；
- first-pass yield；
- 修复后的最终 yield；
- blocked 和 failed 比例；
- 每个资产的 GPU 时间、Isaac Sim 时间和 LLM 成本；
- 人工介入时间；
- 不同资产类别的 macro-average 和 worst-group 表现。

否则，“规模化”只能作为目标，不能作为实验结论。

---

## 3. 与近期相关工作的关系

截至 2026-07-29，以下工作与宽泛的 Agentic Real2Sim、生成—critic—修复和
仿真反馈路线存在明显重叠。

| 工作 | 已覆盖能力 | 对本项目创新定位的影响 |
|---|---|---|
| [SceneSmith](https://arxiv.org/abs/2602.09153) | Designer–Critic–Orchestrator、多阶段资产生成、SAM3/SAM3D、物理属性估计、碰撞体、regenerate/reroute、物理稳定性验证 | “Agent + 视觉/物理分离 + reroute”不能作为宽泛首创 |
| [GRS](https://arxiv.org/abs/2410.15536) | 从真实图像生成仿真任务、测试套件，并由 router 判断修 simulation code 或 test code | “Agent 编写仿真测试脚本 + 错误路由”不能单独作为创新 |
| [Articraft](https://arxiv.org/abs/2605.15187) | Agent 在受限 SDK 中生成关节资产程序并编写验证测试 | Agent 写资产测试已有直接先例 |
| [SAGE](https://research.nvidia.com/labs/dir/sage/) | generators 与 semantic/visual/physics critics 的迭代自修复 | 通用生成—验证—重试闭环已有成熟近邻 |
| [PhysX-Omni](https://arxiv.org/abs/2605.21572) | 几何、绝对尺度、材料、affordance、kinematics、功能描述和 simulation-ready benchmark | “给资产增加物理属性”本身竞争激烈 |
| [Agentic Real2Sim](https://arxiv.org/abs/2607.19190) | 使用视觉语言 Agent 将真实交互记录转换为可仿真的 episodic twin | “Agentic Real2Sim”这一宽泛概念已经被直接提出 |
| [Scalable Real2Sim](https://arxiv.org/abs/2503.00370) | 通过机器人交互、相机和关节力矩识别视觉几何、碰撞几何、质量、质心和惯量 | 真实物性需要交互或测量，单 RGB 只能提供先验 |
| [NVIDIA SimReady Specification](https://docs.omniverse.nvidia.com/simready/latest/overview/simready-spec.html) | typed metadata、物理能力、语义和规则化验证 | 写入 USDPhysics 或通过 schema 检查不等于完整的行为认证 |

因此，以下内容更适合作为系统属性，而不是论文核心创新：

- 多 Agent 串联生成流程；
- 视觉生成与物理 authoring 分离；
- Agent 编写任意仿真脚本；
- structured feedback；
- 失败后重新生成；
- 不修改底层三维生成模型。

更可辩护的创新空隙是：

> **矿业任务条件化的动态认证、具有故障可辨识性的主动测试、资产多阶段根因诊断、
> 最小成本修复，以及证据化选择性认证。**

这一判断应保持谨慎，不宜在论文中轻率使用 “the first”。该方向更新很快，正式投稿前
需要重新检索同期工作。

---

## 4. 推荐的统一方法框架

### 4.1 问题形式化

输入定义为：

$$
x=(I,p,\tau,r)
$$

其中：

- $I$：单张 RGB 图像；
- $p$：资产文本描述；
- $\tau$：目标矿业任务；
- $r$：机器人、尺度和环境约束。

生成资产定义为：

$$
A=(G,C,\theta)
$$

其中：

- $G$：视觉几何；
- $C$：碰撞表示；
- $\theta$：尺度、质量、摩擦、弹性、阻尼、CCD 等物理参数。

Agent 不直接声称资产“正确”，而是根据任务生成可执行契约：

$$
\mathcal K_\tau=\{(T_j,\Omega_j,\phi_j)\}_{j=1}^{M}
$$

其中：

- $T_j$：测试类型；
- $\Omega_j$：姿态、载荷、速度和扰动等测试范围；
- $\phi_j$：确定性的通过谓词或连续裕量。

Isaac Sim 执行测试：

$$
\xi=S(A,\omega), \qquad \omega\in\Omega_j
$$

当：

$$
\phi_j(\xi)<0
$$

系统保存一个可复现反例：

$$
c=(T_j,\omega,\xi,\phi_j(\xi))
$$

诊断 Agent 再判断错误最可能来自：

```text
segmentation
reconstruction
metric scale / orientation
collision representation
mass / inertia
contact material
solver / CCD
test configuration
```

随后执行最小范围修复，而不是无条件重跑完整流程。

### 4.2 两个真正的闭环

```text
结构闭环

RGB
→ mask / geometry
→ 结构证据
→ prompt / mask / seed 修复
```

```text
行为闭环

任务契约
→ 仿真测试
→ 轨迹级反例
→ 根因诊断
→ 最小阶段修复
→ 回归测试
→ 资产认证
```

---

## 5. 候选机制创新

### 5.1 创新点一：任务条件化的可执行资产契约

不同资产不应运行完全相同的通用 drop test，而应根据它们在 benchmark 中承担的任务
定义“什么叫有效”。

例如，一个用于装载和倾倒矿石的开口矿斗可以使用如下契约：

```json
{
  "task": "contain_and_discharge_ore",
  "required_affordances": [
    "accessible_opening",
    "closed_side_walls",
    "gravity_discharge"
  ],
  "tests": [
    {
      "family": "opening_access",
      "probe_radius_ratio": [0.1, 0.3]
    },
    {
      "family": "containment",
      "payload_count": 20,
      "required_retention": 0.95
    },
    {
      "family": "tilt_discharge",
      "tilt_angle_deg": [20, 60]
    }
  ]
}
```

不同类别可对应不同契约：

| 资产类别 | 推荐测试 |
|---|---|
| 矿石、普通刚体 | drop、roll、push、pile stability |
| 锚杆、钻杆、管件 | CCD、高速碰撞、抓取、插入 |
| 桶、料斗、管筒 | opening access、containment、discharge |
| 固定障碍物 | 碰撞对齐、不可穿透、机器人通行间隙 |
| 工具 | 抓取稳定性、接触区域和任务操作 |

可证伪的研究假设是：

> 在相同仿真预算下，任务条件化测试比统一固定测试更能发现影响下游任务的资产缺陷。

当前代码中的 `target_task` 和 `robot_constraints` 已经提供了接口，但它们目前主要被保存
到物理 spec，并没有真正决定测试和认证逻辑。可从
[`RuleBasedPolicy`](../src/mining_asset_pipeline/agent/policy.py)
和资产 brief 开始扩展。

### 5.2 创新点二：主动诊断测试和反例驱动路由

普通测试只能回答“是否失败”。更强的方法需要回答：

> 下一项什么实验最能区分当前候选根因？

例如：

- visual mesh 有开口，但 collider probe 无法进入
  → collider 封口，不应重跑 SAM3D；
- visual mesh 和 collider 都无开口
  → 重建丢失内腔，应更换 mask、seed 或 generator；
- 低速接触正常，但高速穿透
  → CCD、time step 或 collider thickness；
- 推动距离异常
  → 可能是质量或摩擦，可先用倾斜面临界角辨识摩擦，再用已知冲量辨识质量；
- 物体静止时倾倒
  → 质心、尺度、支撑面或初始姿态。

定义故障变量：

$$
D\in\left\{
d_{\mathrm{seg}},
d_{\mathrm{geometry}},
d_{\mathrm{scale}},
d_{\mathrm{collision}},
d_{\mathrm{mass}},
d_{\mathrm{friction}},
d_{\mathrm{CCD}}
\right\}
$$

系统维护当前故障假设 $q(D\mid H)$，并在测试成本约束下选择预期信息增益最大的测试：

$$
T^\ast=
\arg\max_{T\in\mathcal T}
\left[
I(D;Y_T\mid H)-\lambda\,\mathrm{Cost}(T)
\right]
$$

第一版不需要训练新模型，可以采用：

- 有限故障—症状图；
- 规则化症状似然；
- Agent 从受限候选测试中选择；
- Isaac Sim 返回确定性数值证据。

需要通过实验验证：

- 单位仿真成本发现的缺陷数量；
- 根因 top-1/top-k 准确率；
- SAM3D 等昂贵阶段的非必要重跑次数；
- 固定预算下最终认证资产数量；
- repair success 和 regression rate。

### 5.3 创新点三：反例驱动的最小阶段修复

定义有限修复动作集合：

$$
\mathcal R=\left\{
r_{\mathrm{prompt}},
r_{\mathrm{mask}},
r_{\mathrm{seed}},
r_{\mathrm{scale}},
r_{\mathrm{collision}},
r_{\mathrm{physics}},
r_{\mathrm{CCD}},
r_{\mathrm{block}}
\right\}
$$

根据反例选择满足下式的修复动作：

$$
r^\ast=
\arg\min_{r\in\mathcal R(c)}
\left[
\mathrm{Cost}(r)
+\alpha\,\mathrm{Drift}(A,r)
+\beta\,\mathrm{RegressionRisk}(r)
\right]
$$

修复必须满足：

- 修复当前失败谓词；
- 尽量保持已接受的视觉和物理属性；
- 已通过测试不得发生回退；
- 每类动作具有明确预算；
- 无法辨识或无法修复时明确 block；
- 修改某个产物时，只失效其依赖的下游产物和测试。

资产依赖关系可以表示为：

```text
mask
  ↓
geometry
  ├── visual USD
  └── collision representation
          ↓
      physics spec
          ↓
      dynamic tests
          ↓
      certificate
```

修改 friction 时只需重跑相关动态测试；修改 mask 时则应失效 geometry、USD 和全部
下游测试。

### 5.4 创新点四：任务等价物理集合与证据化证书

“物理属性不必非常精细”可以转化为一个更严谨的研究命题：

> 不追求从单张 RGB 恢复唯一的真实物理参数，而是寻找对目标任务行为等价的参数集合。

定义：

$$
\Theta_\tau=
\left\{
\theta\in\Theta_{\mathrm{prior}}
\;\middle|\;
A(\theta)\models\mathcal K_\tau
\right\}
$$

例如：

- 对固定导航障碍物，密度和 restitution 可能不重要，尺度和 collider 很重要；
- 对推动矿石，质量、摩擦和质心很重要；
- 对开口容器，碰撞拓扑可能比密度更重要；
- 对高速细杆，CCD 和碰撞厚度可能比 restitution 更重要。

建议先做 physics sensitivity study：

$$
S_k(\tau)=
\frac{
\Delta\mathrm{TaskOutcome}_\tau
}{
\Delta\theta_k
}
$$

仅校准对目标任务敏感的参数，其余参数输出先验区间和不确定性。

最终 certificate 不应只是由 Agent 自报的 `confidence=0.9`，而应包括：

```text
scale source and interval
tested tasks
parameter perturbation ranges
random seeds and environment configuration
worst-case task margin
success-rate confidence bound
untested capabilities
known assumptions
counterexamples and repairs
Isaac / PhysX version
artifact and trace hashes
```

---

## 6. 绝对尺度与物理可辨识性

### 6.1 当前尺度问题

SAM3D 输出通常是归一化对象。当前 USD 转换采用米制世界，但资产 authoring 阶段没有
自动传入真实尺度校准。

如果尺度误差为 $s$，则对于几何相似的刚体：

$$
m\propto s^3
$$

$$
J\propto s^5
$$

因此，即使密度 profile 本身合理，最终质量和惯量也可能严重错误。

动态认证应强制记录：

```text
scale_source
nominal_scale_m
scale_interval_m
scale_assumption
scale_evidence
```

### 6.2 建议设置两个输入 Track

#### RGB-only

- 输入只有单张 RGB 和描述；
- 输出尺度和物理参数区间；
- 评价任务充分性、不确定性和正确拒绝能力；
- 不声称恢复真实唯一物性。

#### RGB + minimal metadata

额外提供至少一种信息：

- 一个真实尺寸；
- 标尺或标定板；
- 已知机器人夹爪尺度；
- 材料类别；
- 质量；
- 简单交互观测。

该 Track 可以评价尺度和物理参数校准能力。

### 6.3 物理真实性与仿真内部一致性必须区分

需要明确区分：

1. **USD authoring consistency**
   属性是否正确写入；
2. **simulator-internal validity**
   是否稳定、无穿透并满足任务测试；
3. **task-level behavioral equivalence**
   与 reference asset 的任务结果是否一致；
4. **sim-to-real physical fidelity**
   与真实物体交互分布是否一致。

如果没有真实测量或真实交互数据，只能支持前三级中的部分结论，不能直接声称
physics-accurate。

---

## 7. Agent 与确定性脚本的统一方式

技术路线统一不意味着所有组件都必须由 LLM 完成。更严谨的分工是：

```text
Agent
  任务理解、物理假设、测试规划、根因诊断、修复选择

TestDSL
  表达 Agent 选择的测试、参数域和观测量

确定性编译器
  将 TestDSL 编译成 Isaac Sim 测试场景

Isaac Sim
  产生轨迹、速度、接触、穿透和稳定性等物理事实

确定性 Oracle
  计算 retention、penetration、slip、settle time 等指标

Agent
  根据证据选择下一项实验或修复

独立 Certification Gate
  最终 accept / block
```

Agent 仍然贯穿整个方法，因为它决定：

- 测什么；
- 为什么测；
- 下一项实验是什么；
- 修改哪个阶段；
- 是否需要回退、重试或终止。

### 7.1 不建议自由生成任意 Python 测试

自由脚本生成容易产生：

- 测试标准漂移；
- Agent 为自己的资产降低测试难度；
- 测试代码错误被误判为资产错误；
- 不同资产之间无法公平比较；
- 安全和可复现问题；
- Agent 修改 simulator 参数或 oracle 阈值。

建议采用：

> **受限仿真测试程序合成 Agent。**

Agent 只生成 typed JSON/DSL，从固定、版本化的测试原语库中选择测试和合法参数。
最终阈值和 oracle 由 benchmark 固定，Agent 无权修改。

---

## 8. Benchmark 与 Pipeline 的闭合设计

### 8.1 推荐 Track

| Track | 输入与输出 | 核心研究问题 |
|---|---|---|
| Asset Production | RGB、描述、任务条件 → USD | 最终资产是否满足视觉和任务物理要求 |
| Failure Diagnosis | 故障资产和结构化证据 → 根因、责任阶段 | Agent 是否能正确定位错误 |
| Budgeted Repair | 故障资产 + 固定成本预算 → 修复资产 | 局部修复是否优于完整重生成 |
| Selective Certification | 资产 + 任务 → accept/block、证书 | 系统是否知道何时不能可靠判断 |
| Test Planning | 资产、任务 → TestDSL | Agent 设计的测试是否有诊断价值 |

Test Planning 可以作为独立评价 Track，但 Agent 生成的测试不能成为官方资产评分的唯一
oracle。

### 8.2 三层测试机制

#### 固定核心测试

Agent 无权跳过或修改：

- USD 可加载；
- 无 NaN/Inf；
- 单位和尺度合法；
- 碰撞体存在；
- 无初始严重穿透；
- 基础 drop/settle 稳定；
- 必需 metadata 完整。

#### 任务条件化测试

Agent 从版本化模板库中选择：

- opening/containment；
- push/incline；
- CCD/high-speed collision；
- grasp/lift；
- insertion；
- pile/stack；
- clearance/navigation。

#### Agent 自适应压力测试

Agent 根据当前故障假设选择下一项最有诊断价值的测试，用于寻找反例和修复，但不能
决定最终官方排名。

### 8.3 构建测试与官方测试必须隔离

```text
construction tests
Agent 可见，用于寻找反例和修复

hidden certification tests
Agent 不可见，使用不同参数、初态和随机种子

downstream robot tasks
由独立策略或控制器评价

real-world gold subset
具有实测尺寸、质量和简单行为分布
```

否则会产生循环论证：Pipeline 使用自己设计的测试修资产，再使用同一测试证明自己成功。

---

## 9. 故障注入 Benchmark

故障注入是客观评价“诊断和路由”能力的关键。

### 9.1 推荐 Mutation

#### 分割层

- mask 腐蚀；
- mask 膨胀；
- 错误实例；
- 背景残留；
- 任务关键部件被遗漏。

#### 几何层

- 开口被封闭；
- 把手、薄杆或内腔缺失；
- 几何截断；
- 重复部件；
- 非流形或孔洞；
- 错误朝向和原点。

#### 尺度与坐标层

- 整体尺度乘以固定倍数；
- up-axis 错误；
- 单位错误；
- pivot 和质心错位。

#### 碰撞层

- collider 缺失；
- collider 过粗；
- convex hull 封闭开口；
- collision mesh 膨胀或收缩；
- visual/collider 不对齐；
- 接触偏移异常。

#### 物理层

- 质量或密度乘以 0.1、10；
- 摩擦系数异常；
- restitution 异常；
- gravity 错误关闭；
- CCD 缺失；
- dynamic/kinematic 类型错误；
- 质心和惯量错误。

#### 复合故障

- 同时注入两个或多个故障；
- 测试对 unseen fault family 和 unseen composition 的泛化。

### 9.2 每个 Mutation 需要记录

- 真实故障来源阶段；
- 故障严重度；
- 预期可观测症状；
- 允许的修复动作集合；
- 最低成本成功修复路径；
- 该故障是否会影响指定任务；
- 等价 mutation 判定。

某个参数虽然被修改，但如果对目标任务行为没有可观测影响，不应机械地要求系统必须
检测它。

### 9.3 同时收集自然故障

除人工 mutation 外，还应收集：

- SAM3 真实分割失败；
- SAM3D 自然重建失败；
- collider 生成失败；
- Isaac Sim 数值问题；
- 真实 Agent 错误路由；
- 人工判定的不可修复案例。

只使用人工合成故障会削弱外部有效性。

---

## 10. 评价指标

### 10.1 最终资产

#### 视觉与几何

- multi-view silhouette IoU；
- Chamfer distance；
- F-score；
- normal consistency；
- metric-scale error；
- task-critical part completeness；
- opening/cavity preservation。

#### 碰撞与物理

- collider-to-reference distance；
- collision volume overlap；
- opening sealing rate；
- maximum/mean penetration depth；
- settle time；
- sliding distance；
- rebound height；
- containment retention；
- push displacement；
- grasp/lift success；
- simulation real-time factor。

#### 任务一致性

不能只报告机器人任务成功率。错误资产可能使任务异常变简单，反而提高成功率。

还应比较：

- 候选资产与 reference asset 的成功/失败一致性；
- 任务成功率差值；
- 轨迹和终态差异；
- 多个策略在候选资产和 reference asset 上的性能排序相关性。

### 10.2 Agent、诊断与修复

- fixed-budget Task-Certified Asset Rate；
- root-cause macro-F1；
- route accuracy；
- repair success@k；
- non-regression rate；
- false-accept rate；
- false-reject rate；
- blocked/abstain risk–coverage；
- unnecessary expensive-stage reruns；
- SAM3D 调用次数；
- Isaac Sim steps；
- GPU 小时；
- LLM 调用和 token；
- 总延迟；
- quality–cost curve。

### 10.3 Cost-sensitive Routing Regret

可以定义：

$$
\begin{aligned}
\mathrm{RoutingRegret}
&=
\mathrm{Cost}(\text{Agent chosen path})
\\
&\quad -
\mathrm{Cost}(\text{minimum successful repair path})
\end{aligned}
$$

该指标比简单的路由分类准确率更能证明：

> 结构化诊断和局部修复确实减少了不必要的完整重生成。

---

## 11. 必要基线与消融

### 11.1 基线

1. 原始 SAM3 → SAM3D → USD，无修复；
2. 固定 rule/profile pipeline，无 LLM；
3. one-shot LLM 直接生成 physics spec；
4. 单体 Agent，共享一个上下文；
5. 多角色 Agent，但无动态仿真反馈；
6. 当前视觉闭环 + 静态 Loop 1；
7. 固定 dynamic test suite；
8. 随机合法测试顺序；
9. 动态失败后完整重生成；
10. 任务契约 + 主动诊断 + 局部修复；
11. oracle router 上界；
12. 小规模人类专家固定时间预算。

所有方法应共享：

- 相同底层生成器；
- 相同候选 seed 数；
- 相同仿真 query budget；
- 相同最大重试次数；
- 相同可访问 metadata。

### 11.2 关键消融

- 去掉 `target_task`；
- 去掉 `robot_constraints`；
- 去掉动态仿真反例；
- 去掉根因诊断；
- 所有失败都完整重生成；
- 去掉回归测试；
- 固定测试与自适应测试；
- 任意 Python 与受限 DSL；
- Agent 自评与独立 oracle；
- 单点物理参数与参数区间；
- 去掉尺度不确定性；
- 去掉 block/abstain；
- 去掉 deterministic veto；
- 替换不同三维生成 backbone；
- 不同 LLM 和调用预算。

---

## 12. 数据、Ground Truth 与统计设计

### 12.1 Ground Truth

#### 几何

- 独立多视角；
- 结构光或摄影测量扫描；
- 输入只给一张图，其余视角保留用于评价；
- 使用标尺、标定板、CAD 或卡尺获得真实尺度；
- 对开口和内腔进行专门采集。

同时报告：

- 允许刚性对齐后的 shape metric；
- 不允许任意缩放的 metric-scale metric。

#### 物理

小规模 gold subset 至少测量：

- 质量；
- 外形尺寸；
- 材料类别；
- 固定配对表面的静/动摩擦；
- 受控落体下的反弹行为；
- 已知推力下的位移和旋转；
- 容器插入和保持。

接触动力学存在随机性，应使用多次真实实验形成行为分布或置信区间，不能只使用一次
精确轨迹作为唯一 ground truth。

### 12.2 数据切分

以真实物体 identity 为分组单位：

- 同一物体的所有视角、视频帧和 prompt 变体只能位于一个 split；
- 同一拍摄 session 和近重复产品应分组；
- 设置 unseen instance；
- unseen subclass；
- unseen material–category composition；
- unseen site/domain；
- unseen fault family；
- unseen composed faults。

测试集可以使用新采集、未公开的矿业物体，减小基础模型训练数据记忆造成的泄漏。

### 12.3 统计单位

统计单位应是物理对象，而不是数千条 simulation episode，避免伪重复。

建议：

- 同一资产上的不同方法使用 paired comparison；
- 连续指标使用按资产聚类的 paired bootstrap 或 permutation test；
- 二值通过/失败使用 McNemar 或配对精确检验；
- 报告 95% CI 和 effect size；
- 多重比较使用 Holm 校正；
- 同时报告总体、category macro-average 和 worst-group；
- `best-of-N` 必须让所有基线使用相同 $N$，并计入成本。

---

## 13. 最小可行实现

### 13.1 第一版资产范围

建议严格限制在：

- 普通刚体和矿石；
- 细长刚体：钻杆、锚杆、管件；
- 开口容器：桶、料斗、管筒。

暂时不把手推车、阀门、钻机等复杂关节设备作为主要对象。当前流程将它们视为单刚体，
会产生明显的任务语义和动力学错误。

### 13.2 第一版动态测试

1. drop / settle；
2. push / incline；
3. opening access / containment / discharge；
4. high-speed collision / CCD。

### 13.3 建议新增状态

```text
task_contract
→ dynamic_test_planning
→ dynamic_validation
→ diagnosis
→ repair
→ regression_validation
→ certification
```

### 13.4 建议新增受控工具

```text
compile-contract
run-test
record-counterexample
record-diagnosis
apply-repair
run-regression
issue-certificate
```

### 13.5 建议新增输出目录

```text
simulation/
├── contract.json
├── tests/
├── traces/
├── counterexamples/
├── diagnoses/
├── repairs/
├── regressions/
└── certificate.json
```

第一版不需要训练新模型。真正关键的实现工作是：

- TestDSL；
- Isaac Sim 动态测试；
- 结构化行为指标；
- 故障—症状图；
- 最小修复路由；
- mutation benchmark；
- 隐藏认证机制。

---

## 14. 推荐的论文研究问题

### RQ1

静态 schema/VLM 检查能否可靠预测资产的交互就绪性？

### RQ2

在相同仿真预算下，任务条件化测试是否比统一固定测试更有效？

### RQ3

具有故障可辨识性的主动测试是否能够提高根因定位准确率并减少仿真成本？

### RQ4

反例驱动的最小阶段修复是否比失败后完整重生成具有更高认证率、更低成本和更少回归？

### RQ5

证据化资产 certificate 是否能够预测隐藏任务失败，并实现可靠的 selective acceptance？

---

## 15. 推荐的论文贡献表述

不建议写：

> 我们提出一个多 Agent 资产生成框架。

建议改为：

> 我们提出一种面向矿业机器人任务的任务条件化、反例驱动 Agentic 资产合成与认证
> 框架。该框架将冻结的视觉三维生成器视为候选提议器，由 Agent 将任务和机器人约束
> 编译为受限、可执行的物理测试契约；确定性仿真器返回轨迹级反例，诊断 Agent 将
> 失败归因到分割、重建、尺度、碰撞或物理参数层，并执行成本受限的最小阶段修复。
> 最终，系统输出带有适用任务范围、参数不确定性、鲁棒性证据和未覆盖风险的资产证书。

可以将论文贡献归纳为：

1. **任务条件化的可执行资产契约**；
2. **反例驱动的主动诊断与最小修复机制**；
3. **面向矿业交互任务的故障诊断与选择性认证 Benchmark**。

最终方法主线不是：

> Agent + scripts

而是：

> **Agentic hypothesis → experiment → counterexample → diagnosis
> → repair → certification。**

---

## 16. 应避免的论文表述

- “首次提出多 Agent Real2Sim”；
- “从单张 RGB 恢复准确物理属性”；
- “写入 USDPhysics 即 simulation-ready”；
- “只使用一个生成器却声称 model-agnostic”；
- “只有静态检查却称生成—仿真双闭环”；
- “同一个 Agent 生成资产、生成测试并决定自己通过”；
- “只报告成功生成的资产，不计 failed、blocked 和超预算案例”；
- “使用 simulator-only 测试声称真实世界物理准确”。

更稳健的定位是：

> 本研究关注面向矿业 Benchmark 的任务充分性，而非从单图恢复不可辨识的唯一真实
> 物性；通过 Agent 规划受限物理探针、仿真器产生结构化行为证据，并依据反例进行根因
> 定位和最小阶段回退，实现可审计、成本受限的资产认证—修复闭环。
