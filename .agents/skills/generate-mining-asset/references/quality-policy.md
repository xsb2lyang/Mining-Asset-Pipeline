# Static asset quality policy

## Segmentation

Accept a mask only when it selects the intended single subject, preserves task-relevant parts, and excludes most background. Treat no candidates, score below 0.5, mask ratio below 0.5%, above 95%, or invalid boxes as structural failures. A different candidate selection does not consume another GPU inference.

Try no more than three meaningfully different English prompts. Block when the input is ambiguous, occluded, cropped, or cannot be repaired through candidate selection or prompt normalization.

## Reconstruction

Require a non-empty GLB with finite bounds, vertices, faces, and material or vertex-color information. A missing four-view contact sheet is a semantic-review failure in Agent-reviewed mode.

Compare front, right, top, and isometric views with the original and mask. Reject the wrong subject, major missing parts, sealed openings, disconnected critical structure, severe proportions, implausible topology, or lost appearance. Try seeds 42, 43, and 44 at most once each. Do not accept because the retry budget ended.

## Physics

- Preserve open cups, buckets, vessels, and task-relevant tubes with `sdf` or `convexDecomposition`; never use `convexHull` when it seals a required cavity.
- Use CCD for thin, small, or fast movable objects.
- Disable gravity only for fixed or infrastructure assets.
- Require non-negative friction, static friction >= dynamic friction, restitution in [0,1], and linear/angular damping in [0,1].
- Treat density and friction as traceable priors. Do not call them measurements.
- The deterministic Critic has final veto even when a semantic Critic accepts.

## Quality labels

Use `agent_reviewed` only after semantic RGB/mask/geometry review plus independent Physics Author/Critic review and deterministic checks.

Use `degraded` only when all of the following hold:

- the semantic model or host capability was unavailable;
- deterministic visual structure checks passed without an explicit visual rejection;
- both material and collision use specialized, non-generic profiles;
- physics and USD static checks passed;
- the report records the exact fallback reason.

Block generic material or collision fallback, explicit visual errors, exhausted repair attempts, deterministic Critic errors, or static inspection failure.

`complete` does not certify dynamic stability, containment, mass calibration, graspability, articulation, or robot-task success. Those require Loop 2.
