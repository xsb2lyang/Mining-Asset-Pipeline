# Command-line and Agent workflow

This is the public contract for the dual-control-plane asset Agent. Installation is in [setup.md](setup.md).

## Workflow

```text
RGB + rough prompt
  → Input Analyst / asset brief
  → SAM3 attempts + candidate contact sheet + Visual Critic
  → SAM3D seeds 42/43/44 + four-view contact sheet + Visual Critic
  → isolated Physics Author / Critic + deterministic veto
  → GLB → visual.usd → physics.usd → simulation_ready.usd
  → authored-value static inspection → final/asset.usd
```

Manifest v3 uses independent dimensions:

```text
status:  created | running | complete | blocked | failed
phase:   input_analysis | segmentation | reconstruction | visual_review |
         physics_authoring | physics_review | usd_authoring |
         static_validation | finalization
quality: pending | agent_reviewed | degraded
```

Old manifests remain readable but cannot be resumed.

## Control plane A: repository Skill

Codex discovers `.agents/skills/generate-mining-asset`; Claude Code discovers the linked `.claude/skills/generate-mining-asset`. Invoke the Skill with an RGB path and rough prompt. It drives only `scripts/asset_tool.py` actions and never reads a project API key.

The internal tool CLI is machine-readable:

```bash
python scripts/asset_tool.py --help
```

Its exact subcommands and payload contracts are documented inside the Skill at `references/tool-contract.md`.

## Control plane B: embedded Claude API Agent

```bash
python -m pip install -e '.[llm]'
export ANTHROPIC_API_KEY='set-in-shell-only'

python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

Arguments:

| Argument | Required/default | Meaning |
|---|---|---|
| `--image` | new task | Input RGB image |
| `--prompt` | with `--image` | Rough user prompt; the Agent normalizes it |
| `--resume <asset-id>` | alternative to `--image` | Resume a schema-v3 task without repeating successful GPU stages |
| `--asset-category` | empty | Optional semantic hint |
| `--target-task` | empty | Optional task hint |
| `--robot-constraints` | empty | Optional robot hint |
| `--output-root` | `$PIPELINE_OUTPUT_DIR` or `outputs/` | Asset bundle root |
| `--isaac-sim-path` | `$ISAAC_SIM_PATH` | Isaac Sim root containing `python.sh` |
| `--sam3-env` | `$SAM3_ENV`, local config, or `sam3` | SAM3 Conda environment |
| `--sam3d-env` | `$SAM3D_ENV`, local config, or `sam3d-objects` | SAM3D Conda environment |
| `--model` | `$ANTHROPIC_MODEL` or `claude-sonnet-5` | Embedded controller model |
| `--max-llm-calls` | 8 | Per-asset structured call budget |
| `--quiet` | false | Suppress non-result progress |

There is deliberately no API-key CLI argument: credentials come only from the environment. There are no `--rewrite-prompt` or `--use-llm-critic` switches; normalization and role selection belong to the controller.

The maximum eight calls are allocated as Input Analyst 1, Visual Critic 3, Physics Author 2, and Physics Critic 2. Calls use base64 image blocks and JSON-schema structured output. Any API/SDK/parse failure is audited and disables subsequent remote calls for that run.

On success stdout contains:

```text
asset_id=<asset-id>
final_usd=<absolute-path>/final/asset.usd
quality=agent_reviewed|degraded
```

Exit codes are 0 complete, 2 blocked, and 1 invalid/failed.

## Fallback policy

Without a key or SDK, rule-based prompt normalization, Physics Author, and deterministic Critic take over. A result may be delivered as `degraded` only when visual structural checks pass and both material and collision have specialized non-generic profiles. Unknown/generic semantics, explicit visual rejection, exhausted attempts, Critic errors, or failed static inspection produce `blocked`.

Material density and contact parameters are engineering priors with assumptions, not measurements.

## Batch assets

```json
[
  {
    "image": "assets/samples/paper_tube_rgb.png",
    "prompt": "a cardboard tube",
    "asset_category": "open_container",
    "target_task": "",
    "robot_constraints": ""
  }
]
```

```bash
python scripts/batch_pipeline.py --manifest assets/samples/batch_manifest.json --continue-on-error
```

Each entry invokes the same `run_pipeline.py` source of truth in a fresh subprocess.

## Bundle layout

```text
outputs/<asset-id>/
├── manifest.json
├── request.json
├── input/
├── agent/{asset_brief.json,trace.jsonl,decisions/}
├── visual/
│   ├── sam3_attempts/
│   ├── sam3d_attempts/
│   ├── selected.json
│   └── visual_review.json
├── physics/
│   ├── physics_spec.yaml
│   ├── author/
│   ├── critic/
│   ├── visual.usd
│   ├── physics.usd
│   ├── simulation_ready.usd
│   └── inspection.json
└── final/{asset.usd,asset_report.json}
```

All manifest paths are bundle-relative. The final report records controller, model/calls, fallback, selected mask/seed, repair trace, Physics Author/Critic results, assumptions, static inspection, and the Loop 2 boundary.

## Validation boundary

`complete` means the asset passed semantic/static Loop 1 checks. It has not passed dynamic drop, containment, push, grasp, articulation, or task-success tests. Those belong to Loop 2.
