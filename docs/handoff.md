# Maintainer status notes

> Updated 2026-07-18. Code and tests are authoritative if this note drifts.

## Product boundary

Mining Asset Pipeline turns one RGB image and prompt into a statically checked,
physics-authored USD for Isaac Sim 5.1. It is one asset-generation component of
a future mining-robot benchmark, not the complete benchmark.

## Implemented

- SAM3 mask generation with candidate checks and concrete prompt rewriting.
- SAM 3D Objects GLB generation with bounded seed retries and preview fallback.
- Unattended single/batch CLI workflows.
- Per-asset manifests, isolated output directories, logs, and inspection reports.
- Rule-based Physics Author/Critic with maximum three revision rounds.
- Optional Claude API critic with deterministic fallback and audit marker.
- GLB → USD conversion with SAM3D vertex-color material preservation.
- Rigid body, density/mass, collision, friction, restitution, damping, CCD, and
  static schema inspection.
- Licensed sample inputs and release-readiness/community files.

## Current workflow

```text
RGB + prompt
→ SAM3 → automatic mask checks
→ SAM3D → automatic mesh checks
→ deterministic visual quality gate
→ Physics Author/Critic
→ visual.usd → physics.usd → simulation_ready.usd
→ static inspection → final/asset.usd
```

The single and batch CLIs share `AssetWorkflow`; do not duplicate business
logic in command-line wrappers.

## Verification

```bash
python -m unittest discover -s tests/unit
python scripts/doctor.py --json
git diff --check
```

Fast tests use fake tool runners and do not require CUDA or Isaac Sim. Real GPU
and simulation regressions remain separate.

## Important runtime constraints

- Orchestrator: Python 3.11.
- SAM3: dedicated Python 3.12 Conda environment at the pinned submodule.
- SAM3D: dedicated upstream environment; Linux and large NVIDIA GPU required.
- Isaac Sim tools: its own `python.sh` with Conda/Python/CUDA variables cleared.
- Checkpoints are gated and never committed.

## Highest-value next work

1. Loop 2 dynamic tests: drop stability, collision penetration, open-container
   containment, push/contact response, and task-conditioned grasp tests.
2. Mining material/collision profiles for steel, ore, rubber, drill rods, and
   articulated or compound equipment.
3. Render-based visual comparison against the input from multiple viewpoints.
4. Real-environment integration tests with explicit GPU/driver/tool versions.
5. Skills/repair-trajectory persistence after repeated successful fixes.

## Do not regress

- Do not import `anthropic` at module import time or make an API key mandatory.
- Do not let Isaac Sim inherit Conda or PyTorch CUDA libraries.
- Do not use `convexHull` for an open container.
- Do not discard GLB vertex colors during USD conversion.
- Do not write generated assets outside the configured output root.
- Do not commit model weights, credentials, generated USD/GLB/PLY, or private
  input data.

See [cli_pipeline.md](cli_pipeline.md), [setup.md](setup.md), and
[release_checklist.md](release_checklist.md) for operational details.
