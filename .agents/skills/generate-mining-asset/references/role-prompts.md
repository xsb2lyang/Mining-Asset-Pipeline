# Role contracts

## Input Analyst: AssetBrief

Inspect the RGB and rough prompt. Do not invent hidden geometry or measured properties. Save:

```json
{
  "object_name": "plain name",
  "category": "category",
  "sam3_prompts": ["one to three concrete English noun phrases"],
  "material": "ceramic|steel|iron|aluminum|copper|rubber|wood|ore|plastic|unknown",
  "is_open_container": false,
  "is_slender": false,
  "is_fast_or_small": false,
  "is_fixed": false,
  "target_task": "",
  "robot_constraints": "",
  "assumptions": ["explicit uncertainty"]
}
```

The `material` field is a controlled prior label, not a claim of measurement:
map paper/cardboard to `wood`, mineral rock to `ore`, and use `unknown` when
the visible evidence and prompt do not support one of the listed families.

## Visual Critic: VisualDecision

Read only the original RGB, SAM3 contact sheet/report, selected mask, SAM3D four-view sheet/report, and brief. Save one controlled decision:

```json
{
  "action": "accept|select_mask|rewrite_prompt|rerun_sam3d|block",
  "summary": "one-line diagnosis",
  "findings": [{"severity": "error|warning", "code": "snake_case", "message": "specific evidence"}],
  "candidate_index": null,
  "prompt": null,
  "seed": null,
  "reason": null
}
```

Populate only the argument used by the action. The tool restricts seeds to 42/43/44.

## Physics Author: PhysicsSpec

Read the brief, geometry report, the complete nested schema in `configs/physics_spec_template.yaml`, `configs/materials/*.yaml`, and `configs/collision_profiles/*.yaml`. Copy every required nested key from the template. Generate schema version 1 using the canonical fields `asset`, `material`, `mass`, `collision`, `rigid_body`, `assumptions`, and `rationale`. Use an exact repository profile name and its density unless the request supplies a better traceable value. Keep friction/restitution/damping within policy bounds. For density mode, make `mass.density_kg_m3` equal `material.density_kg_m3`; for mass mode, provide a positive `mass.mass_kg`.

The Author must not inspect or anticipate the Critic response. Persist its result before starting the Critic.

## Physics Critic: PhysicsReview

Start from a fresh isolated context when supported. Read only the persisted brief, geometry report, and PhysicsSpec. Save:

```json
{
  "accepted": false,
  "summary": "one-line result",
  "findings": [{"severity": "error|warning", "code": "snake_case", "path": "dotted.path", "message": "specific correction"}]
}
```

Set `accepted` true only with no error findings. Warnings remain advisory. The subsequent deterministic Critic may still reject the spec.
