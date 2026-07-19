# Sample inputs

These two small RGB images and one orbit video are end-to-end examples. They
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

## Scene orbit-video sample

`scenes/mine_tunnel_orbit.mp4` is a 17 MB example of the capture style accepted
by the Phase 1 scene workflow: a slow, continuous orbit around the scene with
no cuts and limited motion blur. It is an input example, not a pre-generated
World Labs result; Marble generation remains an external, potentially billable
operation and may not be bit-for-bit reproducible.

Copyright 2026 Mining Asset Pipeline contributors. The video is distributed
under the repository's [Apache License 2.0](../../LICENSE). Its SHA-256 is
`902c38c2e0118e8e3c973157215ca27911d2dfadc9c23734ccaa1ea08e1723dc`.

After completing the optional scene setup, either ask Codex/Claude Code to use
`generate-mining-scene` with this file, or follow the [scene pipeline
guide](../../docs/scene_pipeline.md#versioned-capture-example). Do not commit
the generated Marble downloads or scene outputs.

Run both examples after completing [local setup](../../docs/setup.md):

```bash
python scripts/batch_pipeline.py \
  --manifest assets/samples/batch_manifest.json \
  --continue-on-error
```
