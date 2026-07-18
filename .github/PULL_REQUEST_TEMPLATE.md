## Problem

What user-visible or engineering problem does this change address?

## Changes

- Describe the main implementation change.

## Validation

List exact commands and results. State whether validation used CUDA, model
weights, an Anthropic API call, or Isaac Sim.

```text
python -m unittest discover -s tests/unit
```

## Checklist

- [ ] I did not commit credentials, model weights, generated assets, or private data.
- [ ] I added or updated tests for changed behavior.
- [ ] I updated public CLI/schema/documentation where applicable.
- [ ] I reviewed third-party licensing for any new dependency or sample data.
