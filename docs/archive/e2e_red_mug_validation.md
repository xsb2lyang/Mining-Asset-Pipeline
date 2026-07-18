# Red mug end-to-end validation

> **Historical record (2026-07-12):** the input and generated red-mug outputs
> are intentionally not distributed with the repository. Use the licensed
> examples in `assets/samples/` for current reproduction. Paths below document
> the original experiment and are not expected to exist in a fresh clone.

This record verifies that the reorganized repository can produce a
simulation-ready USD from the local red-mug sample without relying on the
legacy pipeline entry points.

## Preconditions

- Initialize the SAM3 and SAM3D submodules.
- Install the local `sam3` and `sam3d-objects` Conda environments.
- Set `SAM3_CHECKPOINT_DIR` and `ISAAC_SIM_PATH` as described in
  [setup.md](../setup.md).
- The local red-mug image used in this run is intentionally ignored by Git:
  `Benchmark/Assest_maker/outputs/sam3d_test/images/red_mug.jpg`.

## Validated commands

```bash
conda run -n sam3 python scripts/run_sam3.py \
  --image Benchmark/Assest_maker/outputs/sam3d_test/images/red_mug.jpg \
  --prompt "red mug" \
  --checkpoint "$SAM3_CHECKPOINT_DIR/sam3.pt" \
  --out-dir outputs/e2e_red_mug/sam3

conda run -n sam3d-objects python scripts/run_sam3d.py \
  --image Benchmark/Assest_maker/outputs/sam3d_test/images/red_mug.jpg \
  --mask-npz outputs/e2e_red_mug/sam3/mask.npz \
  --out-dir outputs/e2e_red_mug/sam3d \
  --checkpoint third_party/sam-3d-objects/checkpoints/hf/pipeline.yaml \
  --seed 42

"$ISAAC_SIM_PATH/python.sh" scripts/convert_to_usd.py \
  --input outputs/e2e_red_mug/sam3d/mug.glb \
  --output outputs/e2e_red_mug/usd/mug.usd \
  --single-mesh

"$ISAAC_SIM_PATH/python.sh" scripts/prepare_physics.py \
  --input outputs/e2e_red_mug/usd/mug.usd \
  --output outputs/e2e_red_mug/usd/mug_physics.usd \
  --collision sdf --density 2500

"$ISAAC_SIM_PATH/python.sh" scripts/apply_physics_material.py \
  --input outputs/e2e_red_mug/usd/mug_physics.usd \
  --output outputs/e2e_red_mug/usd/mug_sim.usd \
  --ensure-material \
  --static-friction 0.5 --dynamic-friction 0.4 --restitution 0.05 \
  --friction-combine-mode average --restitution-combine-mode max \
  --enable-ccd \
  --report outputs/e2e_red_mug/usd/mug_physics_report.json

"$ISAAC_SIM_PATH/python.sh" scripts/inspect_physics.py \
  --input outputs/e2e_red_mug/usd/mug_sim.usd \
  --out outputs/e2e_red_mug/usd/inspect_physics.json
```

## Result

The July 12, 2026 run completed successfully. SAM3 selected one `red mug`
candidate with score `0.976`. SAM3D exported GLB, OBJ, and PLY. The final USD
contains one mesh, one rigid body, one MassAPI with density `2500 kg/m^3`, and
one `sdf` collision approximation. Ceramic friction/restitution and CCD are
also applied. Generated files remain under ignored `outputs/`.

`sdf` is preferred for this open container so a convex hull does not seal the
cup opening. It still requires a dynamic containment test before production
use.

## Known runtime warning

This workstation's Isaac Sim command-line sessions currently emit repeated
`Failed to create change watch ... errno=28` messages. The affected commands
completed with exit code zero, and disk/inode capacity was available. Treat
this as a file-watcher-resource warning to resolve separately; it did not
block this validation.
