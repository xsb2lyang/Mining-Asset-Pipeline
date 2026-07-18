---
name: generate-mining-asset
description: Generate a statically physics-ready USD asset from one RGB image and a rough prompt by running the repository's controlled SAM3, SAM3D, visual review, Physics Author/Critic, USD authoring, and static-validation tools. Use when Codex or Claude Code is asked to create, regenerate, review, or resume a mining/robotics simulation asset without using the repository's embedded Claude API controller.
---

# Generate Mining Asset

Act as the controller for the repository's whitelisted asset tools. Do not call the embedded API controller.

## Guardrails

- Work from the repository root returned by `git rev-parse --show-toplevel`.
- Run only `scripts/doctor.py` and `scripts/asset_tool.py` for pipeline actions. Do not construct equivalent GPU or USD shell commands yourself.
- Do not import Anthropic, read `ANTHROPIC_API_KEY`, or invoke `scripts/run_pipeline.py`.
- Keep generated payloads and decisions inside the active `outputs/<asset-id>/` bundle.
- Do not bypass a manifest phase, retry budget, schema error, deterministic Critic error, or failed static inspection.
- Describe `complete` as statically checked only. Never claim Loop 2 drop, containment, grasp, or robot-task validation.

Read [tool-contract.md](references/tool-contract.md) before invoking tools. Read [quality-policy.md](references/quality-policy.md) before visual or final acceptance. Read [role-prompts.md](references/role-prompts.md) before creating the brief or physics specification.

## Workflow

1. Run `python scripts/doctor.py --json`. Stop and report missing required local dependencies.
2. Choose the entry branch. For a new RGB request, create the asset with controller `external_skill` and record the returned ID. For a supplied asset ID, call `status`; continue only when schema is 3 and status is `created` or `running`. Do not create a replacement task. Treat `blocked` as terminal and report its reason; embedded `run_pipeline.py --resume` resumes interrupted `running`/retryable `failed` tasks, not explicit rejections.
3. Inspect the original RGB and rough prompt. Use the host's safe file-editing tool to write payloads only at the allowed bundle paths, then submit `agent/asset_brief.json` with one to three concrete English SAM3 prompts and explicit assumptions. Do not use shell heredocs or scripts to author payloads.
4. Run SAM3 with the first prompt. Inspect the original, candidate contact sheet, and numeric report. Select an existing candidate, try the next brief prompt, or block. When a recorded decision requests a repair, immediately execute its matching `select-mask` or `run-sam3` action. Never rerun an indistinguishable action.
5. Run SAM3D with seeds `42`, `43`, then `44` only as needed. Compare the original, selected mask, and front/right/top/isometric contact sheet. When a decision requests reconstruction repair, record it and immediately invoke `run-sam3d` with the next seed. Accept only when the subject, silhouette, openings, critical parts, and appearance are plausible.
6. Record the structured visual decision. A rejection must request one controlled action; exhausted or unfixable errors must block.
7. Produce a Physics Author spec using profiles and priors. If isolated subagents are available, ask one subagent to author only the spec and a second fresh subagent to critique only the persisted brief, reports, and spec. Do not leak the Author's reasoning to the Critic.
8. Submit the spec, record the semantic Critic payload with `check-physics`, and obey the merged/deterministic findings. Revise at most once by applying only the requested field-level correction; never change geometry or invent a profile to silence a finding.
9. Run `author-usd`, then `finalize` only after the visual review, combined physics review, and static inspection pass.
10. Return only the manifest-recorded final USD path, quality, key assumptions,
    and static inspection summary. The filename is derived from
    `asset_brief.object_name` (for example `paper_tube.usd`); never rename it
    independently of `finalize`. Mention that Loop 2 has not run.

When the host cannot create isolated subagents, perform Author and Critic in two explicitly separated passes: persist the Author output, clear its rationale from working context as far as possible, then critique only the files listed above.
