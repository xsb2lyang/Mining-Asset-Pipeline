# Architecture and repository policy

## Product boundary

This repository owns the orchestration, USD/physics tooling, configurations,
tests, and documentation for a mining-asset generation pipeline. It does not
vendor model weights, an Isaac Sim installation, generated assets, or upstream
SAM repositories.

```text
Prompt + RGB
  → external repository Skill OR embedded Claude controller
  → shared whitelisted AgentTools
  → segmentation and semantic review
  → single-image reconstruction and four-view review
  → USD conversion
  → physical authoring
  → static validation
  → baseline physics-authored asset

Future Loop 2 extends this boundary with dynamic simulation validation before
an asset can be called task-certified or simulation-ready for a benchmark.
```

The separate scene-generation path is:

```text
Marble full-resolution PLY + collider GLB
  → fixed-SH NuRec compatibility conversion
  → separate visual/collision Phase 1 USD assembly
  → portable relative-reference USD package
  → static stage validation
```

## Target source layout

| Path | Responsibility |
|---|---|
| `src/mining_asset_pipeline/` | Importable, reusable pipeline code |
| `scripts/` | Thin CLI entry points that call `src/` |
| `.agents/skills/` | Canonical repository-local Agent Skill |
| `.claude/skills/` | Claude Code discovery link to the canonical Skill |
| `configs/materials/` | Material priors: density, friction, restitution |
| `configs/collision_profiles/` | Collision selection profiles by object class |
| `assets/samples/` | Small licensed inputs and reproducibility manifests |
| `tests/` | Fast unit tests, integration checks, and Isaac-based regression tests |
| `environments/` | Conda/environment variable setup instructions |
| `third_party/` | Pinned upstream submodules; no copied source code |
| `docs/` | User guides, architecture, experiment records, troubleshooting |

## Dependency and data policy

- **SAM3 and SAM3D Objects:** use Git submodules pinned to known commits.
- **3dgrut and WorldComposer:** pinned submodules used by the default PLY-based
  Phase 1 scene path. WorldComposer's missing upstream license is a release
  blocker, documented in `THIRD_PARTY_NOTICES.md`.
- **Model checkpoints:** gated or large; download locally after explicit Hugging
  Face authentication. Never commit weights or tokens.
- **Isaac Sim:** install separately and locate it through `ISAAC_SIM_PATH`.
- **Generated GLB/USD/PLY and simulation outputs:** ignored by Git. Publish a
  curated demonstration asset through GitHub Releases or another data host.
- **Sample inputs:** only small, redistributable inputs plus provenance and
  license information may live under `assets/samples/`.

## Local runtime boundary

The USD implementations live in `src/mining_asset_pipeline/usd/`; supported CLI
entry points live in `scripts/`. Historical workstation directories under
`Benchmark/` are ignored and are not part of the public repository contract.
A fresh clone may place Isaac Sim and checkpoints anywhere and configure their
locations through `environments/local.env`.

Large local scene inputs live under ignored `local_data/scene_inputs/`; scene
jobs live under ignored `scene_outputs/`. A scene's `final/` directory is the
delivery unit because its root USD references packaged dependencies by relative
path.

The security boundary is `AgentTools`: controllers can choose only validated
actions and payloads, never arbitrary subprocess commands or stage output
paths. The Skill control plane does not import Anthropic or read project API
credentials. The embedded control plane reads `ANTHROPIC_API_KEY` only from
the environment and uses the same tools and state machine.
