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

Example:

```bash
bash "$ISAAC_SIM_PATH/python.sh" scripts/inspect_physics.py \
  --input outputs/example.usd \
  --out outputs/example.inspect.json
```
