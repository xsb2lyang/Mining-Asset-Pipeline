"""Step 2 — Run SAM3D Objects on a (image, mask) pair and export OBJ/GLB/PLY.

Run with the dedicated SAM3D Objects environment.

Reads:
  step1_sam3.npz   -- mask / boxes / scores / prompt
  images/red_mug.jpg

Writes (under outputs/sam3d_test/red_mug/):
  mug.ply          -- 3D Gaussian Splat
  mug.glb / mug.obj -- decoded mesh export (best effort)
  summary.json     -- which keys existed in the SAM3D output dict
"""
from __future__ import annotations

# IMPORTANT: do this BEFORE importing inference.py, because inference.py
# imports gradio at the top, and gradio triggers httpx to read ALL_PROXY.
# httpx refuses `socks://...` URLs so the script dies before any work
# happens. We rewrite socks:// proxy URLs to http:// for the duration of
# this run; the SAM3D pipeline itself never reaches out to the network.
import argparse
import json
import os
import sys
import warnings
from pathlib import Path

for _k in ("ALL_PROXY", "all_proxy"):
    _v = os.environ.get(_k, "")
    if _v.startswith("socks://"):
        os.environ[_k] = "http://" + _v[len("socks://"):]

warnings.filterwarnings("ignore")
os.environ["LIDRA_SKIP_INIT"] = "true"  # skip the auto-generated init module

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("PIPELINE_OUTPUT_DIR", REPO_ROOT / "outputs"))
DEFAULT_SAM3D_DIR = Path(os.environ.get("SAM3D_DIR", REPO_ROOT / "third_party" / "sam-3d-objects"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--mask-npz", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, help="Defaults to $PIPELINE_OUTPUT_DIR/<image-stem>/sam3d")
    ap.add_argument("--sam3d-dir", type=Path, default=DEFAULT_SAM3D_DIR)
    ap.add_argument("--checkpoint", type=Path, help="Defaults to <sam3d-dir>/checkpoints/hf/pipeline.yaml")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if not args.image.is_file():
        raise FileNotFoundError(args.image)
    if not args.mask_npz.is_file():
        raise FileNotFoundError(args.mask_npz)
    if not args.sam3d_dir.is_dir():
        raise FileNotFoundError(f"SAM3D checkout not found: {args.sam3d_dir}")
    args.checkpoint = args.checkpoint or args.sam3d_dir / "checkpoints" / "hf" / "pipeline.yaml"
    if not args.checkpoint.is_file():
        raise FileNotFoundError(f"SAM3D checkpoint not found: {args.checkpoint}")
    args.out_dir = args.out_dir or DEFAULT_OUTPUT_ROOT / args.image.stem / "sam3d"
    args.out_dir.mkdir(parents=True, exist_ok=True)

    data = np.load(args.mask_npz, allow_pickle=True)
    mask = data["mask"].astype(bool)
    if mask.ndim == 3:
        mask = mask[..., 0]
    print(f"[step2] mask loaded: shape={mask.shape}, sum={int(mask.sum())}")

    pil_img = Image.open(args.image).convert("RGB")
    rgb = np.array(pil_img)
    print(f"[step2] image loaded: shape={rgb.shape}")

    # The default Inference.__call__ forces a no-mesh, no-texture-bake path so
    # it returns a GaussianSplat only. We override those via the pipeline's
    # underlying run() so we actually get a mesh as well.
    os.chdir(str(args.sam3d_dir))
    sys.path.insert(0, str(args.sam3d_dir / "notebook"))
    from inference import Inference  # noqa: E402

    print(f"[step2] loading pipeline from {args.checkpoint} ...")
    inference = Inference(str(args.checkpoint), compile=False)

    print(f"[step2] running SAM3D reconstruction (seed={args.seed}) ...")
    out = inference(rgb, mask, seed=args.seed)
    print(f"[step2] SAM3D output keys: {list(out.keys())}")

    # 1) save the Gaussian splat as PLY
    ply_path = args.out_dir / "mug.ply"
    if "gs" in out and hasattr(out["gs"], "save_ply"):
        out["gs"].save_ply(str(ply_path))
        print(f"[step2] wrote {ply_path}  ({ply_path.stat().st_size/1e6:.1f} MB)")
    else:
        print("[step2] no gs in output; skipping .ply")
        ply_path = None

    # 2) Find a trimesh-able mesh in the output dict. SAM3D stores mesh as
    # a Python list[trimesh.Trimesh] AND a separate output['glb'] trimesh.Scene.
    # Try the Scene first (single, clean), then a merge of the per-part list.
    import trimesh

    obj_path, glb_path = None, None
    mesh_used = None

    if out.get("glb") is not None:
        scene_or_mesh = out["glb"]
        try:
            glb_path = args.out_dir / "mug.glb"
            scene_or_mesh.export(str(glb_path))
            print(f"[step2] wrote {glb_path} ({glb_path.stat().st_size/1e6:.1f} MB)  [from output['glb']]")
            mesh_used = ("glb", scene_or_mesh)
        except Exception as e:
            print(f"[step2] GLB from output['glb'] failed: {e!r}")
            glb_path = None

    # Sanity-check mesh output: trimesh.Scene has `.export`; list items are
    # SAM3D-internal `MeshExtractResult` objects with torch vertices/faces,
    # so we convert them to trimesh.Trimesh first.
    def _coerce(obj):
        if obj is None:
            return None
        if isinstance(obj, list):
            valid = []
            for m in obj:
                if isinstance(m, trimesh.Trimesh):
                    valid.append(m)
                else:
                    # SAM3D MeshExtractResult carries vertices/faces tensors
                    v = getattr(m, "vertices", None)
                    f = getattr(m, "faces", None)
                    if v is not None and f is not None:
                        try:
                            v_np = v.detach().cpu().numpy() if hasattr(v, "detach") else np.asarray(v)
                            f_np = f.detach().cpu().numpy() if hasattr(f, "detach") else np.asarray(f)
                            valid.append(trimesh.Trimesh(vertices=v_np, faces=f_np, process=False))
                        except Exception as e:
                            print(f"[step2]   skip mesh item {type(m).__name__}: {e!r}")
            if not valid:
                return None
            return trimesh.util.concatenate(valid) if len(valid) > 1 else valid[0]
        return obj

    if obj_path is None:
        mesh_obj = _coerce(out.get("mesh"))
        if mesh_obj is not None:
            try:
                obj_path = args.out_dir / "mug.obj"
                mesh_obj.export(str(obj_path))
                print(f"[step2] wrote {obj_path} ({obj_path.stat().st_size/1e6:.1f} MB)  [from output['mesh']]")
                mesh_used = ("mesh", mesh_obj)
            except Exception as e:
                print(f"[step2] OBJ from output['mesh'] failed: {e!r}")
                obj_path = None
        else:
            print(f"[step2] output['mesh'] was empty (type={type(out.get('mesh')).__name__})")

    if glb_path is None:
        mesh_obj = _coerce(out.get("mesh"))
        if mesh_obj is not None:
            try:
                glb_path = args.out_dir / "mug.glb"
                mesh_obj.export(str(glb_path))
                print(f"[step2] wrote {glb_path} ({glb_path.stat().st_size/1e6:.1f} MB)  [from output['mesh']]")
            except Exception as e:
                print(f"[step2] GLB from output['mesh'] failed: {e!r}")
                glb_path = None

    if obj_path is None and ply_path is not None:
        # Fallback: convert the PLY point cloud to OBJ so the user still
        # has an OBJ on disk even if the pipeline never produced a mesh.
        print("[step2] trying OBJ-from-PLY fallback ...")
        try:
            import trimesh
            pc = trimesh.load(str(ply_path))
            obj_path = args.out_dir / "mug.obj"
            pc.export(str(obj_path))
            print(f"[step2] wrote {obj_path} (from PLY)  ({obj_path.stat().st_size/1e6:.1f} MB)")
        except Exception as e:
            print(f"[step2] PLY->OBJ fallback failed: {e!r}")

    summary = {
        "output_keys": sorted(out.keys()),
        "ply": str(ply_path) if ply_path else None,
        "glb": str(glb_path) if glb_path else None,
        "obj": str(obj_path) if obj_path else None,
        "mesh_used_source": mesh_used[0] if mesh_used else None,
    }
    with open(args.out_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[step2] wrote {args.out_dir/'summary.json'}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
