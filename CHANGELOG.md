# Changelog

This project follows [Semantic Versioning](https://semver.org/) from its first
tagged release. Dates use ISO 8601.

## [Unreleased]

### Added

- Release-readiness documentation, licensed sample manifests, environment
  doctor, packaging checks, and community health automation.
- Pinned 3dgrut and WorldComposer submodules plus a reproducible Real2Sim
  Phase 1 entry point for portable Marble scene USD packages.

### Removed

- The optional Gradio web interface; the supported execution paths are now the
  single-asset and batch CLIs.
- The obsolete stdout-only `validate_asset.py`; static validation now uses
  `inspect_physics.py` exclusively.
- Human visual-review states and interfaces (`ReviewDecision`,
  `submit_review()`, `review_required`, and `visual_approved`).

### Changed

- Moved early workstation and red-mug experiment notes into `docs/archive/` so
  current setup and CLI documentation remain the primary user path.
- Visual checks now continue directly into Physics Author/Critic on success and
  fail the task on deterministic mask or mesh errors. New manifests use schema
  version 2.

## [0.1.0] - 2026-07-18

### Added

- SAM3 → SAM 3D Objects → USD orchestration.
- Unattended single/batch CLIs.
- Persistent per-asset manifests, visual checks, and bounded physics review.
- Rule-based Physics Author/Critic and optional Claude critic with fallback.
- Rigid body, mass/density, collision, physics material, damping, and CCD
  authoring for Isaac Sim 5.1.
- Static USD physics inspection and final asset packaging.

### Fixed

- Preserve SAM3D vertex colors by binding a USD Preview Surface reader.
