#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${THREEDGRUT_ENV:-worldcomposer-r2s}"
PYTORCH_INDEX="https://download.pytorch.org/whl/cu121"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is required but was not found on PATH" >&2
  exit 1
fi

if [[ ! -f "${ROOT}/third_party/3dgrut/pyproject.toml" ]]; then
  echo "3dgrut submodule is missing; run scripts/update_submodules.sh" >&2
  exit 1
fi

if ! conda env list --json | python -c \
  'import json, pathlib, sys; name=sys.argv[1]; data=json.load(sys.stdin); raise SystemExit(0 if any(pathlib.Path(p).name == name for p in data.get("envs", [])) else 1)' \
  "${ENV_NAME}"; then
  conda create -n "${ENV_NAME}" python=3.11 pip -y
fi

conda run -n "${ENV_NAME}" python -m pip install --upgrade pip
conda run -n "${ENV_NAME}" python -m pip install \
  --extra-index-url "${PYTORCH_INDEX}" \
  --constraint "${ROOT}/environments/scene_phase1_constraints.txt" \
  "${ROOT}/third_party/3dgrut"

PYTHONPATH="${ROOT}/third_party/3dgrut" conda run -n "${ENV_NAME}" \
  python -m threedgrut.export.scripts.transcode --help >/dev/null

echo "Scene Phase 1 environment is ready: ${ENV_NAME}"
