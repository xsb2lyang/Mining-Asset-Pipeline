# Scripts

These are the supported command-line entry points. Run the USD-related scripts
with Isaac Sim's `python.sh`, not the current conda Python.

| Script | Purpose |
|---|---|
| `convert_to_usd.py` | Convert GLB/OBJ/FBX/STL geometry to USD |
| `prepare_physics.py` | Add baseline rigid body, mass/density, and collision settings |
| `apply_physics_material.py` | Add friction, restitution, damping, CCD, and contact parameters |
| `inspect_physics.py` | Write a static USD physics validation report |
| `run_sam3.py` | Create a text-conditioned mask from an RGB image (SAM3 env) |
| `run_sam3d.py` | Reconstruct GLB/OBJ/PLY from an RGB image and mask (SAM3D env) |
| `asset_tool.py` | Internal machine-readable whitelist shared by repository Skills and controllers |
| `run_pipeline.py` | Embedded Agent CLI: image + rough prompt → `final/<object_name>.usd` |
| `batch_pipeline.py` | Batch wrapper: JSON manifest → one independent USD asset per entry + summary JSON |
| `doctor.py` | Check local packages, Conda environments, checkpoints, GPU tools, and Isaac Sim |
| `setup_scene_phase1_env.sh` | Create the isolated, constrained 3dgrut transcoder environment |
| `generate_marble_world.py` | Optional Marble API acquisition: RGB image or orbit video → textured mesh + collider GLBs |
| `run_scene_phase1.py` | Marble textured mesh + collider GLBs → renderable Phase 1 scene package |
| `scene_phase1_isaac.py` | Internal Isaac Sim visual/collider assembly helper |
| `record_scene_preview.py` | Render an automatic fly-through or orbit MP4 for a Phase 1 scene |

Example:

```bash
bash "$ISAAC_SIM_PATH/python.sh" scripts/inspect_physics.py \
  --input outputs/example.usd \
  --out outputs/example.inspect.json
```

Use `scripts/launch_isaac_sim.sh` to start the Isaac Sim UI after configuring
`environments/local.env`.

`run_sam3.py` and `run_sam3d.py` require explicit input paths and use
`PIPELINE_OUTPUT_DIR` from `environments/local.env` only as their default
output root. This keeps input data and generated assets outside Git history.

To run the complete pipeline end-to-end, use the unattended CLI:

```bash
python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

Exit codes: `0` complete (writes a semantically named USD under `final/`) / `2` blocked / `1` any other failure.
`ISAAC_SIM_PATH` (env var or `--isaac-sim-path`) is required because the
USD authoring stage invokes Isaac Sim's `python.sh`.

See [the asset-quality workflow](../docs/asset_quality_agent.md) for the
automatic visual checks and Physics Author/Critic stages.

For full-scene conversion, use only the public orchestrator:

```bash
python scripts/run_scene_phase1.py \
  --visual-glb local_data/scene_inputs/example/textured_mesh.glb \
  --collider-glb local_data/scene_inputs/example/collider.glb \
  --scene-name "example tunnel"
```

See [the scene pipeline guide](../docs/scene_pipeline.md). Do not invoke
`scene_phase1_isaac.py` directly except while debugging the Isaac stage.

Before a real run, check the complete local installation:

```bash
python scripts/doctor.py
```
