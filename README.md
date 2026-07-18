# Mining Asset Pipeline

Generate a physics-authored USD asset from one RGB image and a text prompt.
The project combines Meta SAM3, SAM 3D Objects, a bounded asset-quality agent,
and NVIDIA Isaac Sim 5.1.

> **Project status:** experimental `v0.1.0`. The pipeline authors geometry,
> rendering color, rigid-body, mass/density, collision, friction, restitution,
> damping, and CCD attributes, then performs static USD checks. Dynamic
> drop/push/grasp validation is planned for Loop 2, so “complete” currently
> means **static-pipeline complete**, not task-certified in simulation.

## What is implemented

```text
RGB + prompt
  → SAM3 text-conditioned segmentation
  → SAM 3D Objects reconstruction (GLB)
  → deterministic visual quality gate
  → Physics Author / Critic review (rules, optional Claude critic)
  → GLB → visual.usd → physics.usd → simulation_ready.usd
  → static physics inspection → final/asset.usd
```

- Unattended single-asset and batch command-line workflows.
- Batch manifest runner with one isolated output bundle per input.
- Deterministic physics fallback when the optional LLM is unavailable.
- Container-aware collision selection (`sdf`/`convexDecomposition`).
- SAM3D vertex-color preservation through a USD Preview Surface.
- Persistent manifests, inspection reports, tool logs, and physics-review records.

## Repository layout

| Path | Responsibility |
|---|---|
| `src/mining_asset_pipeline/` | Reusable orchestration and USD tooling |
| `scripts/` | Supported command-line entry points |
| `configs/` | Material and collision profiles |
| `assets/samples/` | Small, licensed reproducibility inputs |
| `tests/` | Dependency-light unit tests and future GPU/simulation tests |
| `third_party/` | Pinned SAM3 and SAM 3D Objects submodules |
| `docs/` | Setup, architecture, workflow, and experiment records |
| `Benchmark/` | Ignored legacy/local runtime compatibility area |

Model weights, Isaac Sim, generated GLB/USD files, and API credentials are not
stored in Git.

## Requirements

- Linux x86-64 (validated on Ubuntu 22.04).
- Python 3.11 for the orchestration environment.
- Conda or Mamba; SAM3 and SAM3D use isolated upstream environments.
- NVIDIA GPU and driver. SAM 3D Objects upstream recommends at least 32 GB VRAM.
- NVIDIA Isaac Sim 5.1 installed locally.
- Access to the gated SAM3 and SAM 3D Objects checkpoints on Hugging Face.

The exact upstream source revisions are pinned in `.gitmodules` and the Git
submodule entries. GPU results can still vary with drivers and model kernels;
the stored manifest and validation reports define the reproducibility boundary.

## Installation

### 1. Clone source and pinned submodules

```bash
git clone --recurse-submodules <repository-url>
cd mining-asset-pipeline
```

For an existing clone:

```bash
scripts/update_submodules.sh
```

### 2. Create the orchestration environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Optional features:

```bash
python -m pip install -e '.[llm]'     # Claude physics critic
```

The supported deployment is a source checkout because the complete application
also needs repository configs, scripts, and Git submodules. A built wheel
contains the reusable Python package only; it does not bundle model code,
checkpoints, Isaac Sim, or user-facing sample data.

### 3. Install the model environments

SAM3 uses the environment specified by its pinned upstream revision:

```bash
conda create -n sam3 python=3.12 -y
conda run -n sam3 pip install torch==2.10.0 torchvision \
  --index-url https://download.pytorch.org/whl/cu128
conda run -n sam3 pip install -e third_party/sam3
```

SAM 3D Objects has a larger CUDA/PyTorch3D environment. Follow the pinned
[`doc/setup.md`](third_party/sam-3d-objects/doc/setup.md) from the repository
root and keep the environment name `sam3d-objects`.

### 4. Download gated checkpoints

Authenticate with your own Hugging Face account; never store the token in this
repository.

```bash
hf auth login
hf download facebook/sam3 --local-dir checkpoints/sam3

cd third_party/sam-3d-objects
hf download --repo-type model --local-dir checkpoints/hf-download \
  --max-workers 1 facebook/sam-3d-objects
mv checkpoints/hf-download/checkpoints checkpoints/hf
cd ../..
```

The expected files are:

```text
checkpoints/sam3/sam3.pt
third_party/sam-3d-objects/checkpoints/hf/pipeline.yaml
```

### 5. Configure local paths and verify the machine

```bash
cp environments/local.env.example environments/local.env
# Edit environments/local.env, then load it:
source environments/local.env

python scripts/doctor.py
```

`doctor.py` checks Python packages, both Conda environments, submodules,
checkpoint files, NVIDIA tools, and the Isaac Sim installation without loading
GPU models.

Full details and troubleshooting are in [docs/setup.md](docs/setup.md).

## Run the pipeline

### Reproducible sample

```bash
source .venv/bin/activate
source environments/local.env

python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container
```

The final path is printed as `final_usd=...`. The full asset bundle is written
under `outputs/<asset-id>/`.

Run both licensed samples:

```bash
python scripts/batch_pipeline.py \
  --manifest assets/samples/batch_manifest.json \
  --continue-on-error
```

### Optional Claude physics critic

```bash
python -m pip install -e '.[llm]'
export ANTHROPIC_API_KEY='your-key-in-the-shell-only'
export ANTHROPIC_MODEL='a-model-available-to-your-account'

python scripts/run_pipeline.py \
  --image assets/samples/paper_tube_rgb.png \
  --prompt "a cardboard tube" \
  --asset-category open_container \
  --use-llm-critic
```

If the SDK, key, API, response, or network fails, the workflow records the
fallback and continues with the deterministic critic.

## Output contract

```text
outputs/<asset-id>/
├── manifest.json
├── request.json
├── input/
├── visual/        # mask, GLB, previews, deterministic reports
├── physics/       # specs, critic reviews, USD stages, static inspection
└── final/
    ├── asset.usd
    └── asset_report.json
```

All paths stored in a manifest are relative to the asset bundle. Exit codes are
`0` for complete, `2` for blocked physics review, and `1` for failure.

## Tests

Fast tests do not require CUDA, model weights, or Isaac Sim:

```bash
python -m unittest discover -s tests/unit
git diff --check
```

GPU integration and Isaac Sim regression tests live under `tests/integration/`
and `tests/simulation/` as they are added; they are intentionally not run on
GitHub-hosted CI.

## Known limitations

- Single-image reconstruction cannot recover fully occluded geometry reliably.
- Visual QA is deterministic: failed SAM3/SAM3D checks stop the pipeline, while
  passing checks continue directly to physics review. The checks do not judge
  every semantic or aesthetic defect.
- Physics priors are currently limited and are not a substitute for measured
  material or inertial data.
- Static USD checks do not prove stable contact, containment, graspability, or
  task success. These belong to Loop 2.
- SAM3/SAM3D checkpoints are gated and governed by upstream terms.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Use the
issue templates for reproducible bugs and feature proposals. Report security
or conduct concerns privately as described in [SECURITY.md](SECURITY.md) and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License and third-party software

Project-authored source, documentation, and sample inputs are licensed under
the [Apache License 2.0](LICENSE). SAM3, SAM 3D Objects, Isaac Sim, model
weights, and other dependencies remain under their own licenses and access
terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
