# Scripts

These are the supported command-line entry points. Run the USD-related scripts
with Isaac Sim's `python.sh`, not the current conda Python.

| Script | Purpose |
|---|---|
| `convert_to_usd.py` | Convert GLB/OBJ/FBX/STL geometry to USD |
| `prepare_physics.py` | Add baseline rigid body, mass/density, and collision settings |
| `apply_physics_material.py` | Add friction, restitution, damping, CCD, and contact parameters |
| `inspect_physics.py` | Write a static USD physics validation report |
| `validate_asset.py` | Original stdout-based validator |
| `run_sam3.py` | Create a text-conditioned mask from an RGB image (SAM3 env) |
| `run_sam3d.py` | Reconstruct GLB/OBJ/PLY from an RGB image and mask (SAM3D env) |
| `launch_asset_agent.py` | Launch the local human-in-the-loop Gradio asset-quality workflow |

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

To create and review a complete asset bundle in a browser, run:

```bash
python scripts/launch_asset_agent.py --output-root outputs
```

See [the asset-quality workflow](../docs/asset_quality_agent.md) for the
human approval and physics-confirmation stages.
