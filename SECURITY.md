# Security policy

## Supported versions

Security fixes are applied to the `main` branch and the most recent tagged
release. Experimental historical outputs and third-party submodules are not
maintained by this project; report upstream defects to their owners.

## Reporting a vulnerability

Do not open a public issue for suspected credential exposure, arbitrary code
execution, unsafe model/checkpoint loading, path traversal, or dependency
compromise.

Use GitHub's private vulnerability reporting form:

1. Open the repository's **Security** tab.
2. Select **Advisories** → **Report a vulnerability**.
3. Include affected commit/version, impact, reproduction steps, and a proposed
   mitigation if known.

Maintainers should acknowledge a report within seven days and coordinate a fix
and disclosure timeline with the reporter. If the private form is unavailable,
contact the repository owner through the private contact method listed on their
GitHub profile; do not disclose the details publicly.

## Secrets and local data

- Never commit Hugging Face tokens, Anthropic API keys, Nucleus credentials,
  model weights, generated customer assets, or local environment files.
- Configure credentials through the process environment or a secret manager.
- Revoke any credential immediately if it reaches Git history; deleting the
  working-tree file is not sufficient.

Repository administrators must enable secret scanning, push protection, and
private vulnerability reporting before making the repository public. See
[`docs/release_checklist.md`](docs/release_checklist.md).
