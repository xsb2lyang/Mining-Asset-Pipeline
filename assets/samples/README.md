# Sample inputs

These two small RGB images are end-to-end examples for the asset pipeline. They
were supplied directly by the repository maintainer for this project; they were
not downloaded from a third-party dataset.

Copyright 2026 Mining Asset Pipeline contributors. The images and accompanying
prompts are distributed under the repository's [Apache License 2.0](../../LICENSE).

| File | Recommended prompt | Category | Observed result |
|---|---|---|---|
| `black_slender_device_rgb.png` | `a single rusty iron rod standing upright with a decorative knob near the top and an orange-red insulated wire attached at the tip` | `rod` | Complete USD; convex decomposition |
| `paper_tube_rgb.png` | `a cardboard tube` | `open_container` | Complete USD; SDF preserves the opening |

The prompts are deliberately concise because text-conditioned segmentation can
return zero candidates for long exclusion-heavy descriptions. Generation is
GPU- and model-dependent, so exact mesh topology is not guaranteed. The bundle
manifest and static physics checks are the reproducibility boundary.

Run both examples after completing [local setup](../../docs/setup.md):

```bash
python scripts/batch_pipeline.py \
  --manifest assets/samples/batch_manifest.json \
  --continue-on-error
```
