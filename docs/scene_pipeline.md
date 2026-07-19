# Marble scene → USD: Real2Sim Phase 1

This repository supports a second product path in addition to single-object
asset generation: converting a World Labs Marble scene export into a portable
USD scene package for Isaac Sim.

## Scope

```text
Marble world generation/export (optional Phase 0)
  → full-resolution PLY + collider GLB (+ pano PNG / explicitly requested textured mesh GLB)
  → material-preserving visual GLB-to-USD conversion, or PLY → fixed-SH NuRec compatibility conversion
  → separate visible visual layer and invisible kinematic collision layer
  → relative-reference packaging
  → static USD validation
  → final/<scene_name>.usd
```

This is **Real2Sim Phase 1** only. A completed result contains a visible
reconstruction layer and an invisible, kinematic collider mesh. It has not
passed dynamic collision, navigation, robot-task, or performance validation.

## Runtime boundary

`third_party/3dgrut` and `third_party/WorldComposer` remain pinned upstream
submodules. The default path uses Marble's full-resolution Gaussian PLY through
a pinned NuRec compatibility adapter. Marble PLYs often contain DC colour only,
while the Isaac Sim 5.1 NuRec renderer requires a fixed degree-3 SH tensor. The
adapter pads only the missing higher-order coefficients with zeros; geometry,
opacity, DC colour, scale and rotation remain byte-equivalent after float16
packing. This is the same layout as the historical working Real2Sim export.

Runtime isolation is intentional. Request Marble's optional high-quality
textured mesh only when the user explicitly asks for it and its additional
export cost is justified.

| Runtime | Responsibility |
|---|---|
| Main Python 3.11 environment | Marble acquisition, orchestration, manifests and logs |
| Conda `worldcomposer-r2s` | PLY → fixed-SH NuRec compatibility conversion |
| Isaac Sim 5.1 `python.sh` | Material-preserving GLB conversion, OpenUSD composition and validation |

The entry point clears Conda/CUDA Python environment variables before starting
Kit. Set up the isolated transcoder once when a PLY-only scene is expected:

```bash
scripts/setup_scene_phase1_env.sh
```

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
└── scene.ply               # PLY-only visual input, or provenance when a textured mesh exists

scene_outputs/<scene_name>/
├── manifest.json
├── input/                  # normalized visual input (GLB or PLY) and collider GLB
├── intermediate/           # converted visual/collider USD and optional fixed-SH NuRec USDZ
├── logs/                   # full 3dgrut compatibility-transcode and Isaac Sim logs
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

If Marble did not provide `textured_mesh.glb`, provide its PLY instead. The
orchestrator stages the PLY, runs the isolated compatibility transcoder, then
packages the generated USDZ below `final/assets/visual/` using only relative
references:

```bash
python scripts/run_scene_phase1.py \
  --ply local_data/scene_inputs/example/scene.ply \
  --collider-glb local_data/scene_inputs/example/collider.glb \
  --scene-name "example mine tunnel"
```

Use `--threedgrut-env <name>` only when the isolated environment has a name
other than `worldcomposer-r2s`. Do not invoke 3dgrut's generic `transcode`
command for a DC-only Marble PLY: it writes an empty high-order SH tensor that
can appear black in Isaac Sim 5.1.

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

An explicitly requested high-quality textured mesh can be more color-faithful.
The default PLY compatibility path is also visible in Isaac Sim, but can only
reproduce the colour and geometry information that Marble put in the PLY. If
neither is available, pass the downloaded `pano.png`: the pipeline creates a
visible, pano-projected collider mesh and records `quality: degraded` in the
manifest. This final fallback is renderable and collision-aligned but has
unavoidable single-panorama texture distortion.

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
  --prompt "A subterranean mine tunnel with a gravel pathway"
```

It writes `scene.ply`, `collider.glb`, `pano.png`, and a credential-free
manifest below `local_data/scene_inputs/marble/<world-id>/`. Pass the PLY and
collider files to `run_scene_phase1.py`. Add `--export-hq-mesh` only for an
explicit high-quality-textured-mesh request; it is a separate billable Marble
operation and then writes `textured_mesh.glb` too.

## Versioned capture example

The repository includes
[`assets/samples/scenes/mine_tunnel_orbit.mp4`](../assets/samples/scenes/mine_tunnel_orbit.mp4),
an Apache-2.0-licensed, 17 MB orbit-video input. It is intended as a capture
reference and a real end-to-end input, not as a committed Marble result. After
setting `WORLDLABS_API_KEY` in your shell, run the default non-HQ path:

```bash
python scripts/generate_marble_world.py \
  --video assets/samples/scenes/mine_tunnel_orbit.mp4 \
  --display-name "Subterranean mine tunnel"
```

For a session Agent, invoke `generate-mining-scene` with the same video. The
Skill performs the equivalent acquisition, Phase 1 conversion, static report,
and real preview checks. Generated downloads and `scene_outputs/` remain
ignored local artifacts.

When the high-quality mesh export is unavailable, produce a visible but
degraded scene directly from the included panorama and collider:

```bash
python scripts/run_scene_phase1.py \
  --pano local_data/scene_inputs/marble/<world-id>/pano.png \
  --collider-glb local_data/scene_inputs/marble/<world-id>/collider.glb \
  --scene-name "example mine tunnel"
```

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
