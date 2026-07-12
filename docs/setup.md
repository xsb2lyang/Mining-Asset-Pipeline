# Local setup

## Clone dependencies

```bash
git clone --recurse-submodules <repository-url>
cd mining-asset-pipeline
```

For an existing clone:

```bash
scripts/update_submodules.sh
```

The repository pins SAM3 and SAM3D Objects as submodules under `third_party/`.
Their model weights are not included.

## Configure local paths

```bash
cp environments/local.env.example environments/local.env
```

Set absolute paths in `environments/local.env` for Isaac Sim, model checkpoints,
and generated outputs. The local file is ignored by Git.

## Model access

SAM3 and SAM3D model weights require access granted by their upstream Hugging
Face model pages. Authenticate with your own account, then download weights to
the local directories configured above. Do not commit checkpoints or tokens.

## Launch Isaac Sim

```bash
scripts/launch_isaac_sim.sh
```

The launcher intentionally clears conda, `PYTHONPATH`, and external CUDA
library variables before launching Isaac Sim. This prevents the PyTorch/CUDA
loader conflict observed when the application inherited a conda environment.
