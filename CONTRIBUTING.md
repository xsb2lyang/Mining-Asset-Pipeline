# Contributing

Thank you for improving Mining Asset Pipeline.

## Development boundaries

- Do not commit model weights, Hugging Face tokens, Isaac Sim installations,
  generated GLB/USD/PLY files, or local output directories.
- Keep project code under `src/` and user-facing entry points under `scripts/`.
- Keep third-party source code in pinned submodules under `third_party/`; do
  not copy it into the main repository.
- Add small, redistributable regression fixtures only under `tests/fixtures/`.

## Before opening a pull request

```bash
python -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

If your change needs a GPU, model weights, or Isaac Sim, document the exact
environment and a concise verification result in the pull request description.

## Commit style

Use focused commits such as `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, or
`build:`. Keep generated assets out of commits.
