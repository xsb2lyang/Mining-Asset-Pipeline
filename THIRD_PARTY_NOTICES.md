# Third-party notices

The Apache-2.0 license at the repository root applies only to project-authored
content. The complete pipeline also depends on separately licensed software and
gated model files.

| Component | Source | Local location | License/terms |
|---|---|---|---|
| SAM3 | <https://github.com/facebookresearch/sam3> | `third_party/sam3/` | See `third_party/sam3/LICENSE` and its model terms |
| SAM 3D Objects | <https://github.com/facebookresearch/sam-3d-objects> | `third_party/sam-3d-objects/` | See `third_party/sam-3d-objects/LICENSE` and its model terms |
| NVIDIA Isaac Sim | <https://developer.nvidia.com/isaac/sim> | User-provided installation | NVIDIA software license terms |
| Anthropic Python SDK/API | <https://github.com/anthropics/anthropic-sdk-python> | Optional environment dependency | SDK license and API terms |

Model weights are not redistributed by this repository. Users must obtain them
from the official providers and comply with access restrictions. A dependency
being compatible with this workflow does not relicense it under Apache-2.0.
