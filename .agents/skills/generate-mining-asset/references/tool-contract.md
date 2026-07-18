# Controlled tool contract

All commands run from the repository root. Put global options before the subcommand. Every command prints exactly one JSON object to stdout; full tool logs live in the asset bundle.

Set `PIPELINE_OUTPUT_DIR`, `SAM3_ENV`, `SAM3D_ENV`, and `ISAAC_SIM_PATH` in the environment when defaults do not apply. Never pass an output file path to a stage command.

## Commands

```bash
python scripts/asset_tool.py create \
  --image /absolute/input.png --prompt "rough prompt" \
  --controller external_skill

python scripts/asset_tool.py status --asset-id <id>
python scripts/asset_tool.py record-brief --asset-id <id> --payload outputs/<id>/agent/asset_brief.json
python scripts/asset_tool.py run-sam3 --asset-id <id> --prompt "concrete English object phrase"
python scripts/asset_tool.py select-mask --asset-id <id> --candidate-index 0
python scripts/asset_tool.py run-sam3d --asset-id <id> --seed 42
python scripts/asset_tool.py record-visual-review --asset-id <id> --payload outputs/<id>/agent/decisions/visual.json
python scripts/asset_tool.py submit-physics --asset-id <id> --payload outputs/<id>/physics/author/spec.yaml
python scripts/asset_tool.py check-physics --asset-id <id> --payload outputs/<id>/physics/critic/semantic_review.json
python scripts/asset_tool.py author-usd --asset-id <id>
python scripts/asset_tool.py finalize --asset-id <id> --quality agent_reviewed
```

Omit `check-physics --payload` only when no semantic Critic can run. Such output may be finalized only as `degraded`, with `--fallback-reason`, and only under the specialized fallback policy.

## Phase preconditions

- `record-brief`: created/input analysis.
- `run-sam3`, `select-mask`: segmentation; maximum three distinct prompts.
- `run-sam3d`: selected mask exists; seeds are restricted to 42/43/44.
- `record-visual-review`: a structural mask and GLB report exist. `block` is terminal until explicitly resumed.
- `submit-physics`: accepted visual review exists; maximum two Author rounds.
- `check-physics`: a persisted spec exists. Deterministic checks always run and are unioned with semantic findings.
- `author-usd`: combined physics review is accepted and `ISAAC_SIM_PATH/python.sh` exists.
- `finalize`: visual, physics, and static inspection are accepted.

Successful SAM3/SAM3D calls with the same prompt/seed are idempotent and reuse the stored attempt. Read `status` after interruption. Do not mutate manifests manually. Assets whose manifest schema is not 3 are read-only and cannot resume.

## Payload locations

If the optional category, task, or robot constraints are known, append their flags with real values. Never copy the word `optional` literally.

Use `$PIPELINE_OUTPUT_DIR/<id>` when the output-root environment variable is set; otherwise use `outputs/<id>`. Write Agent-authored payloads only under these locations:

- `outputs/<id>/agent/asset_brief.json`
- `outputs/<id>/agent/decisions/*.json`
- `outputs/<id>/physics/author/*.yaml`
- `outputs/<id>/physics/critic/*.json`

The tool copies validated current values to canonical locations and records relative artifact paths. `record-visual-review` records a requested repair but does not execute it; immediately call the matching `select-mask`, `run-sam3`, or `run-sam3d` command.

`blocked` is a terminal quality decision for this tool interface. `status` may inspect it, but no later action may silently resume or overwrite it.
