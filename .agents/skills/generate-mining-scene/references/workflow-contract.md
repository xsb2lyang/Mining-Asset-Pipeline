# Workflow Contract

Run commands from the repository root. Inputs must be local files. A video must end in `.mp4`, `.mov`, or `.mkv`; any non-video input is treated as one panoramic RGB image.

## Preflight

Use read-only checks. Never echo the key value.

```bash
test -n "${WORLDLABS_API_KEY:-}"
python -c "import requests"
test -n "${ISAAC_SIM_PATH:-}" && test -x "$ISAAC_SIM_PATH/python.sh"
command -v conda
conda run -n "${THREEDGRUT_ENV:-worldcomposer-r2s}" python -c "import torch"
test -d third_party/3dgrut
```

If a check fails, stop and return only the relevant repair instruction:

- Missing key: set `WORLDLABS_API_KEY` in the shell that launches the Agent; do not place it in repository files.
- Missing `requests`: `python -m pip install -e '.[scene]'`
- Missing Isaac Sim path: `export ISAAC_SIM_PATH=/absolute/path/to/isaac-sim-5.1.0`
- Missing `worldcomposer-r2s` or `3dgrut`: `bash scripts/setup_scene_phase1_env.sh`

Do not automatically execute any repair command.

## Marble acquisition

Pick a lowercase hyphenated semantic name, such as `mine-tunnel` or `shaft-interior`. Use the user's description as `--display-name`; omit `--prompt` when none was supplied. Keep Marble's default PLY resolution (`full_res`).

```bash
python scripts/generate_marble_world.py \
  --video /absolute/path/orbit.mp4 \
  --display-name "Mine tunnel" \
  --prompt "optional scene guidance"
```

For a panorama, replace `--video` with `--image`. Add `--export-hq-mesh` only after an explicit user request for an HQ/high-quality textured mesh. The script writes:

```text
local_data/scene_inputs/marble/<world-id>/
  marble_manifest.json
  scene.ply
  collider.glb
  pano.png                 # when Marble provides it
  textured_mesh.glb        # only after the explicit HQ request
```

Read `marble_manifest.json`; do not infer a world ID from logs. Set `scene_name=<semantic-name>-<first-eight-world-id-characters>`.

## Phase 1 assembly

Use `scene_outputs/` as the output root. Never use `--force` in a new task. The normal PLY path is:

```bash
python scripts/run_scene_phase1.py \
  --ply local_data/scene_inputs/marble/<world-id>/scene.ply \
  --collider-glb local_data/scene_inputs/marble/<world-id>/collider.glb \
  --scene-name <scene-name> \
  --output-root scene_outputs \
  --isaac-sim-path "$ISAAC_SIM_PATH" \
  --threedgrut-env "${THREEDGRUT_ENV:-worldcomposer-r2s}"
```

For an explicit HQ request with a successful export, replace `--ply ...` with `--visual-glb .../textured_mesh.glb`. Only if the selected visual source is unavailable or fails, and `pano.png` exists, make a fresh `<scene-name>-pano` bundle:

```bash
python scripts/run_scene_phase1.py \
  --pano local_data/scene_inputs/marble/<world-id>/pano.png \
  --collider-glb local_data/scene_inputs/marble/<world-id>/collider.glb \
  --scene-name <scene-name>-pano \
  --output-root scene_outputs \
  --isaac-sim-path "$ISAAC_SIM_PATH"
```

The final package is `scene_outputs/<actual-scene-name>/`. Its delivery candidate is `final/<actual-scene-name>.usd`; the authoritative static result is `final/static_validation.json`.

## Real preview

After static validation passes, use Isaac Sim's Python launcher, always retain frames, and always render the full visual layer.

```bash
"$ISAAC_SIM_PATH/python.sh" scripts/record_scene_preview.py \
  --scene scene_outputs/<actual-scene-name>/final/<actual-scene-name>.usd \
  --output scene_outputs/<actual-scene-name>/preview.mp4 \
  --camera-mode flythrough \
  --visual-mode full \
  --frames 48 --fps 12 --keep-frames --overwrite
```

Use `--camera-mode orbit` for a panorama input. Inspect the first, middle, and last retained PNG frame. Preview files, frame directories, logs, and intermediates remain inside the scene package and are not the primary deliverable.
