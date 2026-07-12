#!/usr/bin/env bash
# Launch Isaac Sim without inheriting conda/PyTorch/CUDA library contamination.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ENV="${ROOT}/environments/local.env"

if [[ -f "${LOCAL_ENV}" ]]; then
  # shellcheck disable=SC1090
  source "${LOCAL_ENV}"
fi

: "${ISAAC_SIM_PATH:?Set ISAAC_SIM_PATH in environments/local.env or the shell.}"

exec env \
  -u CONDA_PREFIX -u CONDA_DEFAULT_ENV -u CONDA_SHLVL \
  -u CONDA_EXE -u CONDA_PYTHON_EXE -u CONDA_PROMPT_MODIFIER \
  -u PYTHONPATH -u PYTHONHOME -u LD_LIBRARY_PATH \
  "${ISAAC_SIM_PATH}/isaac-sim.sh" "$@"
