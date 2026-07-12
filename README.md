# Mining Asset Pipeline

> Experimental pipeline for turning a text prompt and an RGB image into a
> simulation-ready mining asset for NVIDIA Isaac Sim.

## Status

The current prototype has validated the following path with a red mug sample:

```text
Prompt + RGB → SAM3 mask → SAM3D GLB → USD → rigid body/collision/mass
             → physics material → static schema validation
```

The next milestones are automated geometry validation, collision selection,
and dynamic drop/push/grasp/stack regression tests.

## Repository layout

```text
├── src/mining_asset_pipeline/  # Reusable project Python package
├── scripts/                    # User-facing pipeline entry points
├── configs/                    # Material and collision profiles
├── environments/               # Reproducible environment specifications
├── tests/                      # Unit, integration, and simulation tests
├── third_party/                # Pinned upstream Git submodules (planned)
├── docs/                       # Architecture, setup, and experiment notes
└── Benchmark/                  # Legacy local workspace; migration in progress
```

`Benchmark/` currently contains local third-party checkouts, gated weights,
Isaac Sim, and generated assets. These are intentionally ignored by Git. See
[architecture.md](docs/architecture.md) for the target layout and dependency
policy.

## Quick start

1. Follow [local setup](docs/setup.md).
2. Read [the pipeline overview](docs/sam3_to_sam3d_pipeline.md).
3. Read [the USD/physics record](docs/asset_usd_pipeline.md).

## Documentation

- [Architecture and repository policy](docs/architecture.md)
- [Local setup](docs/setup.md)
- [SAM3 → SAM3D pipeline record](docs/sam3_to_sam3d_pipeline.md)
- [USD conversion and physics pipeline record](docs/asset_usd_pipeline.md)
- [Physics material parameter reference](docs/apply_physics_material.md)
- [Legacy local workspace setup](docs/legacy_workspace_setup.md)

## License

The project license is intentionally not selected yet. A license must be
chosen before publishing the repository. Upstream SAM3, SAM3D Objects, Isaac
Sim, and model weights remain subject to their own licenses and access terms.
