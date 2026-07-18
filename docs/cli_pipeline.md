# Command-line pipeline

This is the authoritative reference for the unattended and batch command-line
interfaces. For installation, start with [setup.md](setup.md).

## Workflow

```text
create bundle
  → SAM3 segmentation and deterministic candidate checks
  → SAM3D reconstruction (up to three meaningful seed attempts)
  → automatic visual approval in CLI mode
  → Physics Author writes spec
  → Physics Critic accepts or requests bounded revision (maximum 3 rounds)
  → GLB → visual.usd
  → rigid body + mass/density + collision → physics.usd
  → physics material + damping + CCD → simulation_ready.usd
  → static inspection → final/asset.usd
```

The Gradio path uses the same `AssetWorkflow`, but pauses for human visual
approval. The CLI intentionally does not perform that human gate.

## Prerequisites

```bash
source .venv/bin/activate
source environments/local.env
python scripts/doctor.py
```

The workflow invokes SAM3 and SAM3D through their Conda environments and Isaac
Sim through its own `python.sh`. It strips incompatible Conda/CUDA environment
variables from Isaac subprocesses automatically.

## Single asset

```bash
python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

Arguments:

| Argument | Required/default | Meaning |
|---|---|---|
| `--image` | required | Input RGB image |
| `--prompt` | required | Concrete text prompt for segmentation |
| `--asset-category` | empty | Semantic category for physics policy |
| `--target-task` | empty | Task hint persisted in the request |
| `--robot-constraints` | empty | Robot constraint hint persisted in the request |
| `--output-root` | `$PIPELINE_OUTPUT_DIR` or `outputs/` | Bundle root |
| `--isaac-sim-path` | `$ISAAC_SIM_PATH` | Isaac Sim root containing `python.sh` |
| `--sam3-env` | `$SAM3_ENV` or `sam3` | Conda environment name |
| `--sam3d-env` | `$SAM3D_ENV` or `sam3d-objects` | Conda environment name |
| `--rewrite-prompt` | false | Apply deterministic concrete-noun rewriting |
| `--use-llm-critic` | false | Request optional Claude physics review |
| `--anthropic-api-key` | `$ANTHROPIC_API_KEY` | API key; never persisted |
| `--anthropic-model` | `$ANTHROPIC_MODEL` or code default | Model identifier |
| `--quiet` | false | Suppress stage progress |

Exit codes:

| Code | State | Contract |
|---:|---|---|
| `0` | `complete` | `final/asset.usd` exists and static checks passed |
| `2` | `blocked` | Physics review did not converge; no final USD |
| `1` | `failed`/invalid | Tool, input, environment, or unexpected-state failure |

On success, stdout ends with machine-readable lines:

```text
asset_id=<asset-id>
final_usd=<absolute-path>/final/asset.usd
```

## Prompt guidance

SAM3 is more reliable with a short visible noun phrase than a long description
containing many exclusions. For example, `a cardboard tube` succeeded on the
sample where a long exclusion-heavy prompt returned zero candidates.

`--rewrite-prompt` applies deterministic domain mappings such as “platform
trolley” → “flatbed cart with handle and wheels”. It does not call an LLM.

## Optional Claude critic

```bash
python -m pip install -e '.[llm]'
export ANTHROPIC_API_KEY='set-in-shell-only'
export ANTHROPIC_MODEL='a-model-available-to-your-account'

python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container \
  --use-llm-critic
```

The optional critic uses dependency injection and lazy SDK import. Missing
credentials, import errors, network/API failures, timeouts, and malformed JSON
all fall back to `PhysicsCriticAgent`. Fallback summaries contain
`[fallback: <ExceptionType>]` for auditability. A successful LLM review writes
`policy: claude_physics_critic_v1` in `physics_review_*.json`.

## Batch assets

Manifest format:

```json
[
  {
    "image": "assets/samples/paper_tube_rgb.png",
    "prompt": "a cardboard tube",
    "asset_category": "open_container",
    "target_task": "",
    "robot_constraints": "",
    "rewrite_prompt": false
  }
]
```

Run:

```bash
python scripts/batch_pipeline.py \
  --manifest assets/samples/batch_manifest.json \
  --continue-on-error
```

Each item runs in a fresh subprocess through `run_pipeline.py`. The batch
wrapper writes a summary containing status, exit code, asset ID, final path,
and a bounded stderr tail. Without `--continue-on-error`, processing stops at
the first blocked or failed item.

## Bundle layout

```text
outputs/<timestamp>-<slug>-<shortid>/
├── manifest.json
├── request.json
├── input/source.<ext>
├── visual/
│   ├── sam3/{mask.npz,meta.json,preview.png}
│   ├── sam3d/{mug.glb,mug.obj,mug.ply,preview.png}
│   ├── sam3_report.json
│   ├── geometry_report.json
│   └── review.json
├── physics/
│   ├── physics_proposal.json
│   ├── physics_spec.yaml
│   ├── physics_review_001.json
│   ├── visual.usd
│   ├── physics.usd
│   ├── simulation_ready.usd
│   ├── material_report.json
│   └── inspection.json
└── final/{asset.usd,asset_report.json}
```

All manifest artifact paths are relative to the bundle. Replaced visual
versions are archived lazily under `history/`.

## Current validation record

The licensed samples under `assets/samples/` were run on Ubuntu 22.04 with two
RTX 4090 GPUs and Isaac Sim 5.1:

- Rod/wire sample: completed with `convexDecomposition`.
- Open cardboard tube: completed with `sdf`, preserving the opening.

Exact meshes are model/driver dependent. The invariant result is a complete
bundle whose static inspection reports mesh, collision, rigid body, and mass
API checks as passing.

## Failure diagnosis

1. Run `python scripts/doctor.py --json`.
2. Read `manifest.json` status/events.
3. Inspect the corresponding `visual/logs/` or `physics/logs/` file.
4. For blocked physics review, inspect every `physics_review_*.json`.
5. Shorten the prompt if SAM3 returns zero candidates.

## Boundary

The CLI performs static asset QA. It does not yet run drop, push, containment,
grasp, or task-success simulation. Those tests belong to Loop 2 and must be
completed before describing an asset as task-certified.
