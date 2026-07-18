# Maintainer status notes

> Updated 2026-07-18. Code and tests are authoritative if this note drifts.

## Product boundary

Mining Asset Pipeline turns one RGB image and a rough prompt into a statically checked, physics-authored USD for Isaac Sim 5.1. It is the asset-generation component of a future mining-robot benchmark, not the complete benchmark.

## Implemented

- Manifest-v3 controlled `AgentTools` with machine-readable `asset_tool.py` commands, attempt isolation, trace, budgets, quality, and stage-level resume.
- Repository Skill for Codex and Claude Code, with no project Anthropic API call.
- Embedded Claude controller with base64 visual inputs, JSON-schema outputs, four isolated roles, and an eight-call budget.
- SAM3 candidate contact sheets and controlled mask selection.
- SAM3D front/right/top/isometric contact sheets and seeds 42/43/44.
- Independent Physics Author/Critic records and deterministic safety veto.
- Material priors for ceramic, steel, iron, aluminum, copper, rubber, wood/cardboard, ore/rock, and plastic.
- GLB → USD conversion with vertex-color preservation, rigid-body/mass/collision/material authoring, and expected-value static inspection.
- Specialized deterministic fallback as `degraded`; generic fallback is blocked.
- Single and batch CLI workflows, licensed samples, and public repository metadata.

## Current workflow

```text
RGB + rough prompt
→ external repository Skill OR embedded Claude API controller
→ shared AgentTools
→ semantic brief → SAM3 review → SAM3D four-view review
→ Physics Author / Critic + deterministic veto
→ visual.usd → physics.usd → simulation_ready.usd
→ static inspection → final/<object_name>.usd
```

## Verification

```bash
python -m unittest discover -s tests/unit
python scripts/doctor.py --json
python "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" \
  .agents/skills/generate-mining-asset
git diff --check
```

Fast tests use fake tool runners and need no CUDA, Isaac Sim, Anthropic package, or key.

## Runtime constraints

- Orchestrator: Python 3.11.
- SAM3: isolated Conda environment and gated local checkpoint.
- SAM3D: isolated upstream environment, Linux, and a large NVIDIA GPU.
- Isaac Sim: its own `python.sh`; Conda/CUDA variables are cleared.
- Embedded Claude: optional `llm` extra; key only from the shell.

## Highest-value next work

1. Loop 2 dynamic drop, contact, containment, grasp, and task tests.
2. Real GPU forward tests for the Skill and embedded controller on paper tube, slender rod, ambiguous prompt, and API interruption cases.
3. Calibrated mining material/interaction measurements to replace broad priors.
4. Articulated and compound equipment support.

## Do not regress

- Do not let controllers pass arbitrary shell commands or output paths.
- Do not import Anthropic at base-package module import time or require a key for Skill/tests.
- Do not allow an LLM acceptance to bypass deterministic Critic errors.
- Do not use `convexHull` when it seals a task-relevant opening.
- Do not discard GLB color during USD conversion.
- Do not mutate schema-v2/older tasks or repeat successful GPU stages on resume.
- Do not commit model weights, credentials, generated assets, private input data, or local Claude settings.

See [cli_pipeline.md](cli_pipeline.md), [setup.md](setup.md), and [release_checklist.md](release_checklist.md).
