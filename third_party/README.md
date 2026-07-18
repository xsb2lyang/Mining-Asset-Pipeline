# Third-party source

This directory contains pinned Git submodules, not copied or vendored project
code:

| Path | Upstream | Purpose |
|---|---|---|
| `sam3/` | `facebookresearch/sam3` | Text-conditioned image segmentation |
| `sam-3d-objects/` | `facebookresearch/sam-3d-objects` | Single-image 3D reconstruction |

Initialize them with:

```bash
git submodule update --init --recursive
```

Do not commit modifications, model checkpoints, or generated outputs inside a
submodule. Each project and its checkpoints remain subject to the license and
access terms shipped by that upstream project. See
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
