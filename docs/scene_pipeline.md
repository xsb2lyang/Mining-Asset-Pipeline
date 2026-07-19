# Marble scene → USD: Real2Sim Phase 1

This repository supports a second product path in addition to single-object
asset generation: converting a World Labs Marble scene export into a portable
USD scene package for Isaac Sim.

## Scope

```text
Marble world generation/export (optional Phase 0)
  → textured mesh GLB + collider GLB (+ optional PLY provenance)
  → material-preserving visual GLB-to-USD conversion
  → separate visible visual layer and invisible kinematic collision layer
  → relative-reference packaging
  → static USD validation
  → final/<scene_name>.usd
```

This is **Real2Sim Phase 1** only. A completed result contains a visible,
textured mesh reconstruction and an invisible, kinematic collider mesh. It has
not passed dynamic collision, navigation, robot-task, or performance
validation.

## Runtime boundary

`third_party/3dgrut` and `third_party/WorldComposer` remain pinned upstream
submodules for historical experiments and future extensions. The renderable
Phase 1 path does not use legacy NuRec: Isaac Sim 5.1 does not render that
payload reliably. It converts Marble's high-quality textured mesh directly.

Runtime isolation is intentional:

| Runtime | Responsibility |
|---|---|
| Main Python 3.11 environment | Marble acquisition, orchestration, manifests and logs |
| Isaac Sim 5.1 `python.sh` | Material-preserving GLB conversion, OpenUSD composition and validation |

The entry point clears Conda/CUDA Python environment variables before starting
Kit. A separate 3dgrut Conda environment is no longer required for the
renderable Phase 1 path.

## Installation

Initialize the pinned upstream revisions:

```bash
scripts/update_submodules.sh
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
├── textured_mesh.glb       # required visible scene mesh
├── collider.glb            # required physics mesh
└── scene.ply               # optional Marble provenance

scene_outputs/<scene_name>/
├── manifest.json
├── input/                  # normalized visual and collider GLBs
├── intermediate/           # converted visual and collider USD files
├── logs/                   # full 3dgrut and Isaac Sim logs
└── final/
    ├── <scene_name>.usd
    ├── static_validation.json
    └── assets/
        ├── visual/<scene_name>_visual.usd
        └── collider/<scene_name>_collider.usd
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
  --visual-glb local_data/scene_inputs/example/textured_mesh.glb \
  --collider-glb local_data/scene_inputs/example/collider.glb \
  --ply local_data/scene_inputs/example/scene.ply \
  --scene-name "example mine tunnel"
```

The command refuses to replace an existing scene bundle. Use `--force` only
when replacement is intentional. On success it prints `scene_usd=...` and
writes SHA-256 input hashes, pinned submodule revisions, parameters, artifacts,
status and limitations to `manifest.json`.

## Record a preview video

Run the preview script through Isaac Sim's own Python. It creates a temporary
camera, captures a fly-through along the collider's longest horizontal axis,
and writes an MP4 under `final/preview/` without modifying the source scene:

```bash
"$ISAAC_SIM_PATH/python.sh" scripts/record_scene_preview.py \
  --scene scene_outputs/example_mine_tunnel/final/example_mine_tunnel.usd
```

Use `--camera-mode orbit` for an exterior overview, `--keep-frames` to retain
the rendered PNGs, `--show-ui` to keep the Isaac Sim window visible, and
`--overwrite` to replace an existing preview.

The renderable Phase 1 output has a visible textured-mesh layer, so the default
preview is color-faithful. `--visual-mode auto` still recognizes historical
NuRec bundles and falls back to their collider for compatibility; new bundles
should not need that fallback.

## Marble API boundary

Marble generation is an optional upstream acquisition stage, not a dependency
of Phase 1. It may download the same PLY and collider GLB layout, but Phase 1
also accepts files exported manually or produced on another machine. A Marble
API credential must come only from `WORLDLABS_API_KEY` in the process
environment and must never appear in config files, manifests, logs, tests or
commits.

The supported optional acquisition command accepts either one RGB image or one
local orbit video. Marble supports `.mp4`, `.mov`, and `.mkv` video inputs.
For an orbit video, keep the target near the frame centre, make one slow,
continuous circuit, and avoid cuts or motion blur:

```bash
python -m pip install -e '.[scene]'
export WORLDLABS_API_KEY='set-this-in-the-shell-only'

python scripts/generate_marble_world.py \
  --video local_data/scene_inputs/tunnel_orbit.mp4 \
  --display-name "example mine tunnel" \
  --prompt "A subterranean mine tunnel with a gravel pathway" \
  --export-hq-mesh
```

It writes `scene.ply`, `collider.glb`, `textured_mesh.glb` and a credential-free
manifest below `local_data/scene_inputs/marble/<world-id>/`. Pass the textured
mesh and collider files to `run_scene_phase1.py`; the PLY is optional
provenance. High-quality mesh export is a separate billable Marble operation.

For a world that was generated before this option existed, export only the
missing visual mesh without regenerating the world:

```bash
python scripts/generate_marble_world.py \
  --world-id <world-id> \
  --output-root local_data/scene_inputs/marble
```

WorldComposer currently has no license file in its pinned upstream repository.
Keeping it as a submodule preserves provenance but does not grant redistribution
rights; resolve its licensing with the upstream author before a public release.
