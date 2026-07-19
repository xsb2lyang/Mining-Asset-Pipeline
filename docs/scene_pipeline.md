# Marble scene → USD: Real2Sim Phase 1

This repository supports a second product path in addition to single-object
asset generation: converting a World Labs Marble scene export into a portable
USD scene package for Isaac Sim.

## Scope

```text
Marble world generation/export (optional Phase 0)
  → Gaussian splat PLY + collider GLB
  → 3dgrut PLY-to-NuRec conversion
  → WorldComposer GLB-to-USD and aligned scene assembly
  → relative-reference packaging
  → static USD validation
  → final/<scene_name>.usd
```

This is **WorldComposer Real2Sim Phase 1** only. A completed result contains a
visible Gaussian reconstruction and an invisible, kinematic collider mesh. It
has not passed dynamic collision, navigation, robot-task, or performance
validation.

## Why two submodules and three runtimes

`third_party/3dgrut` and `third_party/WorldComposer` are pinned Git submodules.
The repository does not copy either upstream codebase. 3dgrut converts the PLY
to the NuRec USDZ format consumed by Isaac Sim 5.1; WorldComposer supplies the
alignment and scene-authoring behavior.

Runtime isolation is intentional:

| Runtime | Responsibility |
|---|---|
| Main Python 3.11 environment | Validation, orchestration, manifest and logs |
| Conda `worldcomposer-r2s` | Pinned 3dgrut transcoder dependencies |
| Isaac Sim 5.1 `python.sh` | GLB conversion, OpenUSD composition and validation |

Do not install 3dgrut into Isaac Sim or run Isaac Sim from the Conda
environment. The entry point clears Conda/CUDA Python environment variables
before starting Kit.

## Installation

Initialize the pinned upstream revisions:

```bash
scripts/update_submodules.sh
```

Create the dedicated transcoder environment:

```bash
scripts/setup_scene_phase1_env.sh
```

The setup script installs the pinned 3dgrut source with compatibility
constraints from `environments/scene_phase1_constraints.txt`. Set a different
environment name before setup if required:

```bash
export THREEDGRUT_ENV=my-scene-env
scripts/setup_scene_phase1_env.sh
```

Copy and edit local paths:

```bash
cp environments/local.env.example environments/local.env
source environments/local.env
```

`ISAAC_SIM_PATH` must identify Isaac Sim 5.1 and contain `python.sh`.

## Input and output locations

Large inputs and generated scenes are intentionally ignored by Git:

```text
local_data/scene_inputs/<scene_name>/
├── scene.ply
└── collider.glb

scene_outputs/<scene_name>/
├── manifest.json
├── input/                  # normalized collider filename for Asset Converter
├── intermediate/           # converted Gaussian and collider USD files
├── logs/                   # full 3dgrut and Isaac Sim logs
└── final/
    ├── <scene_name>.usd
    ├── static_validation.json
    └── assets/
        ├── <scene_name>_gaussian.usdz
        └── <scene_name>_mesh.usd
```

Deliver the complete `final/` directory, not the root USD alone. The root USD
uses relative references into `final/assets/`, so the directory can be copied
to another computer without retaining paths from the generating workstation.
All three authored stages use `1.0 metersPerUnit`; the static report fails if
the assembled stage or either packaged dependency is not metric.

## Run Phase 1

```bash
source environments/local.env

python scripts/run_scene_phase1.py \
  --ply local_data/scene_inputs/example/scene.ply \
  --glb local_data/scene_inputs/example/collider.glb \
  --scene-name "example mine tunnel"
```

The command refuses to replace an existing scene bundle. Use `--force` only
when replacement is intentional. On success it prints `scene_usd=...` and
writes SHA-256 input hashes, pinned submodule revisions, parameters, artifacts,
status and limitations to `manifest.json`.

## Marble API boundary

Marble generation is an optional upstream acquisition stage, not a dependency
of Phase 1. It may download the same PLY and collider GLB layout, but Phase 1
also accepts files exported manually or produced on another machine. A Marble
API credential must come only from `WORLDLABS_API_KEY` in the process
environment and must never appear in config files, manifests, logs, tests or
commits.

The supported optional acquisition command is:

```bash
python -m pip install -e '.[scene]'
export WORLDLABS_API_KEY='set-this-in-the-shell-only'

python scripts/generate_marble_world.py --image local_data/rgb_inputs/tunnel.jpg
```

It writes `scene.ply`, `collider.glb` and a credential-free manifest below
`local_data/scene_inputs/marble/<world-id>/`. Pass the first two files to
`run_scene_phase1.py`; the API operation is not repeated during Phase 1.

WorldComposer currently has no license file in its pinned upstream repository.
Keeping it as a submodule preserves provenance but does not grant redistribution
rights; resolve its licensing with the upstream author before a public release.
