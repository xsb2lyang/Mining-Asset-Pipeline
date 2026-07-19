# Quality Policy

## Accepted Phase 1 result

Report `phase1_verified` only when all of the following are true:

1. `final/static_validation.json` exists and reports a passing static validation result.
2. The final USD exists at the manifest/package final path and its references remain portable within the scene package.
3. A real Isaac Sim preview was rendered with `--visual-mode full --keep-frames`.
4. The first, middle, and last preview frame show loaded scene content; none is fully black, empty, or an obvious unloaded renderer view.

Name the visual source accurately: `HQ mesh` only for an explicit and successful HQ export; `PLY NuRec` for the default fixed-SH PLY compatibility path.

## Degraded result

Only a validated `pano fallback` may be returned as `degraded`. It must still pass the static report and real preview checks. State that the original HQ/PLY visual source failed and that the panorama is a fallback, not an equivalent reconstruction.

## Blocked result

Return `blocked` and the concrete reason when any of the following occurs:

- preflight requirements are missing;
- Marble acquisition fails or lacks a collider;
- static validation fails;
- HQ/PLY rendering is black, empty, or visibly unloaded and no panorama fallback is available;
- the panorama fallback itself fails static or preview validation.

Do not classify an exhausted retry budget, an API error, or a preview failure as success. `phase1_verified` and `degraded` describe static Phase 1 only: they do not claim dynamic physics, navigation, containment, grasping, or robot-task validation.
