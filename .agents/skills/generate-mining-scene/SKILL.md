---
name: generate-mining-scene
description: Generate a visible, portable Phase 1 USD scene from one local orbit video or panoramic RGB image using Marble and the repository scene tools. Use when Codex or Claude Code is asked to create, regenerate, or validate a mining or robotics simulation scene without an embedded API controller.
---

# Generate Mining Scene

Act as the controller for the repository's fixed Marble-to-Phase-1 workflow. This Skill delivers a static scene only; it does not certify dynamics, navigation, or robot-task behaviour.

Read [workflow-contract.md](references/workflow-contract.md) before running the workflow and [quality-policy.md](references/quality-policy.md) before accepting any output.

## Guardrails

- Work from the repository root returned by `git rev-parse --show-toplevel`.
- For pipeline work, call only `scripts/generate_marble_world.py`, `scripts/run_scene_phase1.py`, and `scripts/record_scene_preview.py`, plus the read-only preflight checks in the contract.
- Do not import Anthropic, invoke an embedded LLM controller, read `ANTHROPIC_API_KEY`, or print, store, or commit `WORLDLABS_API_KEY`.
- Never install dependencies, change environments, or create credentials silently. A failed preflight is terminal for this run; return the repair command from the contract.
- Accept one local `.mp4`, `.mov`, or `.mkv` orbit video, or one panoramic RGB image. A description is optional.
- Use Marble's `full_res` PLY plus collider by default. Add `--export-hq-mesh` only when the user explicitly asks for HQ or a high-quality textured mesh.
- Keep each task isolated by its Marble world ID. Use `<semantic-name>-<world-id-first-8>` for `--scene-name`; do not overwrite an existing scene bundle with `--force`.

## Workflow

1. Run the preflight. Stop immediately if a required capability is missing.
2. Inspect the source and derive a short semantic display name from the user description or filename. Preserve any uncertainty as an assumption; Marble can caption an omitted description.
3. Generate the Marble world with the appropriate `--video` or `--image` input. Read its `marble_manifest.json` and use its world ID and downloaded paths as the source of truth.
4. Choose the visual layer in this strict order:
   - use `textured_mesh.glb` only if HQ was explicitly requested and the export exists;
   - otherwise use `scene.ply` through the fixed-SH NuRec compatibility path;
   - use `pano.png` only when the preferred visual path is unavailable or fails validation.
5. Run Phase 1 with the collider and selected visual input. Read `final/static_validation.json`; do not finalize a failed static check.
6. Run a short real Isaac Sim preview with `--visual-mode full --keep-frames`: use `flythrough` for a video source and `orbit` for a panorama source. Inspect the first, middle, and last PNG frames. Reject black, empty, or visibly unloaded renders.
7. If the HQ/PLY visual path fails static or preview validation and `pano.png` exists, create a separate `<scene-name>-pano` Phase 1 bundle using only the panorama fallback, rerun static validation and preview, and mark the result `degraded`. If no usable panorama fallback exists, report `blocked` rather than claiming success.
8. Return only the final USD path, quality (`phase1_verified` or `degraded`), visual source (`HQ mesh`, `PLY NuRec`, or `pano fallback`), and the statement that only static Phase 1 validation has run.
