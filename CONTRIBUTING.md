# Contributing

Thank you for improving Mining Asset Pipeline.

## Start here

1. Read [the setup guide](docs/setup.md) and clone with submodules.
2. Create a focused branch from `main`.
3. Keep dependency-light tests runnable without CUDA or model weights.
4. Open an issue before large schema, state-machine, or architecture changes.

## Development boundaries

- Do not commit model weights, Hugging Face tokens, Isaac Sim installations,
  generated GLB/USD/PLY files, or local output directories.
- Keep project code under `src/` and user-facing entry points under `scripts/`.
- Keep third-party source code in pinned submodules under `third_party/`; do
  not copy it into the main repository.
- Add user-facing sample inputs under `assets/samples/` only with explicit
  provenance and redistribution terms. Test-only fixtures belong in
  `tests/fixtures/`.

## Development install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Before opening a pull request

```bash
python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

Update documentation and tests in the same pull request when changing a public
CLI, manifest field, state transition, physics schema, or output path.

If your change needs a GPU, model weights, or Isaac Sim, document the exact
environment and a concise verification result in the pull request description.

## Commit style

Use focused commits such as `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, or
`build:`. Keep generated assets out of commits.

## Pull requests

- Explain the problem and the chosen boundary of the fix.
- List exact verification commands and whether they used a GPU/Isaac Sim.
- Do not attach gated checkpoints, third-party datasets, secrets, or generated
  assets without redistribution rights.
- Keep unrelated formatting or cleanup out of functional changes.

By contributing, you agree that your contribution is licensed under the
repository's Apache License 2.0 and that you have the right to submit it.
