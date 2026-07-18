# Public release checklist

Run this checklist for the first public push and every tagged release.

## Local repository

- [ ] `git status --short` is empty.
- [ ] `python -m unittest discover -s tests/unit` passes.
- [ ] `git diff --check` passes.
- [ ] `python -m build` succeeds from a clean environment.
- [ ] Reachable Git history has been scanned for secrets.
- [ ] New sample data has documented provenance and redistribution terms.
- [ ] Submodules are pinned and show no leading `-` or `+` in
      `git submodule status`.
- [ ] README, changelog, version, and known limitations match the code.

## GitHub repository settings

- [ ] Add a concise description and topics such as `isaac-sim`, `robotics`,
      `usd`, `3d-generation`, and `mining`.
- [ ] Enable Issues and private vulnerability reporting.
- [ ] Enable secret scanning and push protection.
- [ ] Protect `main`: require pull requests and the `repository-checks` status.
- [ ] Disable force pushes and branch deletion on `main`.
- [ ] Confirm Dependabot alerts and updates are enabled.
- [ ] Verify the Community Standards checklist recognizes the license,
      contribution guide, conduct policy, security policy, and issue templates.

## Release

- [ ] Create an annotated `vX.Y.Z` tag from a clean, reviewed commit.
- [ ] Publish release notes from `CHANGELOG.md`.
- [ ] Do not upload gated model weights or third-party assets.
- [ ] If publishing demonstration USDs, use GitHub Releases and include source
      image licensing, tool versions, manifest, and validation report.
- [ ] Verify a fresh `git clone --recurse-submodules` using the public URL and
      follow `docs/setup.md` without relying on the maintainer workstation.

The repository cannot configure these remote settings before a GitHub remote
exists. They are mandatory publication steps, not optional documentation.
