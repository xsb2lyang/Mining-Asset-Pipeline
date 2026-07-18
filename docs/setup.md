# Reproducible local setup

This guide prepares a fresh Linux clone for the complete RGB + prompt → USD
workflow. The project deliberately isolates its Python runtimes because the
model projects, 3dgrut and Isaac Sim have incompatible CUDA/Python requirements.

| Runtime | Purpose | Expected version/source |
|---|---|---|
| `.venv` | Orchestration, CLI, tests, optional LLM | Python 3.11 |
| Conda `sam3` | Text-conditioned segmentation | Python 3.12; pinned SAM3 submodule |
| Conda `sam3d-objects` | Single-image 3D reconstruction | Pinned upstream environment |
| Conda `worldcomposer-r2s` | Optional scene PLY → NuRec transcoding | Pinned 3dgrut source |
| Isaac Sim `python.sh` | USD conversion and physics schemas | Isaac Sim 5.1 |

## 1. Hardware and operating system

- Linux x86-64; Ubuntu 22.04 is the validated platform.
- NVIDIA driver compatible with the CUDA versions required by both model
  submodules.
- SAM 3D Objects upstream recommends at least 32 GB GPU VRAM.
- Enough disk space for Isaac Sim, environments, and gated checkpoints
  (approximately 45 GB for the validated local installation).

Windows/macOS native execution is not currently supported. WSL is not part of
the validated path because Isaac Sim and GPU rendering add additional limits.

## 2. Clone pinned source

```bash
git clone --recurse-submodules <repository-url>
cd mining-asset-pipeline
git submodule status
```

Both lines from `git submodule status` must begin with a space, not `-` or `+`.
For an existing clone:

```bash
scripts/update_submodules.sh
```

Do not run `git pull` inside either submodule: that defeats source pinning.

## 3. Orchestration environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Install only the optional features you use:

```bash
python -m pip install -e '.[llm]'
python -m pip install -e '.[dev]'
```

The Anthropic SDK is optional. No project API key is required for the
repository Skill or for tests. The unattended embedded controller reads
`ANTHROPIC_API_KEY` only from the shell; without it, specialized deterministic
fallback may produce `quality=degraded`, while generic assets are blocked.

## 4. SAM3 environment

The pinned SAM3 revision currently requires Python 3.12 and CUDA-enabled
PyTorch. Follow its README if upstream installation metadata differs from this
snapshot.

```bash
conda create -n sam3 python=3.12 -y
conda run -n sam3 pip install torch==2.10.0 torchvision \
  --index-url https://download.pytorch.org/whl/cu128
conda run -n sam3 pip install -e third_party/sam3
```

The project runner includes a narrowly scoped inference workaround for the
observed `addmm_act` dtype mismatch on RTX 4090-class GPUs. Do not patch the
submodule itself; keeping it pristine preserves reproducibility.

## 5. SAM 3D Objects environment

Use the exact instructions at
[`third_party/sam-3d-objects/doc/setup.md`](../third_party/sam-3d-objects/doc/setup.md):

```bash
cd third_party/sam-3d-objects
mamba env create -f environments/default.yml
mamba activate sam3d-objects

export PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121"
pip install -e '.[dev]'
pip install -e '.[p3d]'
export PIP_FIND_LINKS="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html"
pip install -e '.[inference]'
./patching/hydra
cd ../..
```

If installation fails, consult the pinned upstream document first; its build
commands are authoritative for that submodule revision.

## 6. Optional scene Phase 1 environment

Only users converting Marble PLY + collider GLB scenes need this environment:

```bash
scripts/setup_scene_phase1_env.sh
```

It is isolated from both model environments and Isaac Sim. Full instructions
and the output package contract are in [scene_pipeline.md](scene_pipeline.md).

## 7. Gated checkpoints

Request access to:

- `facebook/sam3`
- `facebook/sam-3d-objects`

Authenticate locally with `hf auth login`. Tokens must never be written to
`environments/local.env`, Git configuration, fixtures, logs, or documentation.

```bash
mkdir -p checkpoints/sam3
hf download facebook/sam3 --local-dir checkpoints/sam3

cd third_party/sam-3d-objects
hf download --repo-type model --local-dir checkpoints/hf-download \
  --max-workers 1 facebook/sam-3d-objects
mv checkpoints/hf-download/checkpoints checkpoints/hf
cd ../..
```

Verify:

```bash
test -f checkpoints/sam3/sam3.pt
test -f third_party/sam-3d-objects/checkpoints/hf/pipeline.yaml
```

Checkpoint licenses and geographic access rules are controlled by their
upstream providers.

## 8. Isaac Sim 5.1

Install Isaac Sim outside the Git repository or under an ignored local runtime
directory. `ISAAC_SIM_PATH` must point to a directory containing both
`python.sh` and `isaac-sim.sh`.

The workflow clears Conda, `PYTHONPATH`, `PYTHONHOME`, and `LD_LIBRARY_PATH`
before invoking `python.sh`. This prevents PyTorch/CUDA libraries from leaking
into Kit.

## 9. Local configuration

```bash
cp environments/local.env.example environments/local.env
```

Edit the paths, then:

```bash
source environments/local.env
python scripts/doctor.py
```

Useful variants:

```bash
python scripts/doctor.py --require-llm
python scripts/doctor.py --json
```

`environments/local.env` is ignored. Keep secrets in your shell or a secret
manager, never in that file.

## 10. Smoke tests

Dependency-light test suite:

```bash
python -m unittest discover -s tests/unit
```

Check the individual model stages before a full run:

```bash
conda run -n sam3 python scripts/run_sam3.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --out-dir outputs/smoke/sam3

conda run -n sam3d-objects python scripts/run_sam3d.py \
  --image assets/samples/paper_tube_rgb.png \
  --mask-npz outputs/smoke/sam3/mask.npz \
  --out-dir outputs/smoke/sam3d
```

Full pipeline:

```bash
python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

## 11. Common failures

| Symptom | Check |
|---|---|
| `conda: command not found` | Conda/Mamba shell initialization and `PATH` |
| SAM3 checkpoint missing | `SAM3_CHECKPOINT_DIR/sam3.pt` |
| SAM3 returns zero candidates | Use a shorter concrete noun prompt |
| SAM3D checkpoint missing | `SAM3D_CHECKPOINT_DIR/pipeline.yaml` |
| Isaac Sim rejects Conda | Use project workflow or `scripts/launch_isaac_sim.sh` |
| USD appears grey | Ensure current converter authored `VertexColorMaterial` |
| Container opening is sealed | Use `sdf` or `convexDecomposition`, not `convexHull` |
| Scene PLY transcode cannot import 3dgrut | Run `scripts/setup_scene_phase1_env.sh` and check `THREEDGRUT_ENV` |
| Scene root USD works only on its source machine | Deliver the complete `final/` package produced by `run_scene_phase1.py` |

For architecture and output semantics, continue with
[architecture.md](architecture.md) and [cli_pipeline.md](cli_pipeline.md).
