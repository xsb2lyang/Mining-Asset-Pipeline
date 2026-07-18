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
| `run_pipeline.py` | Unattended CLI: image + prompt → `final/asset.usd` (no human in the loop) |
| `batch_pipeline.py` | Batch wrapper: JSON manifest → one independent USD asset per entry + summary JSON |
| `doctor.py` | Check local packages, Conda environments, checkpoints, GPU tools, and Isaac Sim |

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

Exit codes: `0` complete (writes `final/asset.usd`) / `2` blocked
(Author/Critic did not converge in 3 rounds) / `1` any other failure.
`ISAAC_SIM_PATH` (env var or `--isaac-sim-path`) is required because the
USD authoring stage invokes Isaac Sim's `python.sh`.

See [the asset-quality workflow](../docs/asset_quality_agent.md) for the
automatic visual checks and Physics Author/Critic stages.

Before a real run, check the complete local installation:

```bash
python scripts/doctor.py
```
