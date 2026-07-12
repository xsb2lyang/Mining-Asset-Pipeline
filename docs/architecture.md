# Architecture and repository policy

## Product boundary

This repository owns the orchestration, USD/physics tooling, configurations,
tests, and documentation for a mining-asset generation pipeline. It does not
vendor model weights, an Isaac Sim installation, generated assets, or upstream
SAM repositories.

```text
Prompt + RGB
  → segmentation
  → single-image reconstruction
  → USD conversion
  → physical authoring
  → simulation validation
  → simulation-ready asset
```

## Target source layout

| Path | Responsibility |
|---|---|
| `src/mining_asset_pipeline/` | Importable, reusable pipeline code |
| `scripts/` | Thin CLI entry points that call `src/` |
| `configs/materials/` | Material priors: density, friction, restitution |
| `configs/collision_profiles/` | Collision selection profiles by object class |
| `tests/` | Fast unit tests, integration checks, and Isaac-based regression tests |
| `environments/` | Conda/environment variable setup instructions |
| `third_party/` | Pinned upstream submodules; no copied source code |
| `docs/` | User guides, architecture, experiment records, troubleshooting |

## Dependency and data policy

- **SAM3 and SAM3D Objects:** use Git submodules pinned to known commits.
- **Model checkpoints:** gated or large; download locally after explicit Hugging
  Face authentication. Never commit weights or tokens.
- **Isaac Sim:** install separately and locate it through `ISAAC_SIM_PATH`.
- **Generated GLB/USD/PLY and simulation outputs:** ignored by Git. Publish a
  curated demonstration asset through GitHub Releases or another data host.
- **Sample inputs:** only small, redistributable inputs plus provenance and
  license information may live under `assets/samples/`.

## Legacy workspace migration

`Benchmark/Assest_maker/asset_pipeline/isaac/` is the current source of the
USD tools. It will be moved into `src/mining_asset_pipeline/usd/` after tests
and compatibility entry points are established. The misspelled legacy path is
kept temporarily to avoid breaking the proven local workflow.
