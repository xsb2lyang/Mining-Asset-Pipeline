"""Step 1 — Run SAM3 to produce mask + boxes.

Run with the dedicated SAM3 environment.
Reads the RGB image and text prompt, writes:
  step1_sam3.npz   -- mask (bool), boxes (float), scores (float), prompt
  step1_preview.png -- visualization
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import torch
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("PIPELINE_OUTPUT_DIR", REPO_ROOT / "outputs"))
DEFAULT_SAM3_DIR = Path(os.environ.get("SAM3_DIR", REPO_ROOT / "third_party" / "sam3"))
DEFAULT_CHECKPOINT = Path(
    os.environ.get("SAM3_CHECKPOINT_DIR", REPO_ROOT / "checkpoints" / "sam3")
) / "sam3.pt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out-dir", type=Path, help="Defaults to $PIPELINE_OUTPUT_DIR/<image-stem>/sam3")
    ap.add_argument("--sam3-dir", type=Path, default=DEFAULT_SAM3_DIR)
    ap.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    args = ap.parse_args()

    if not args.image.is_file():
        raise FileNotFoundError(args.image)
    if not args.sam3_dir.is_dir():
        raise FileNotFoundError(f"SAM3 checkout not found: {args.sam3_dir}")
    if not args.checkpoint.is_file():
        raise FileNotFoundError(f"SAM3 checkpoint not found: {args.checkpoint}")
    args.out_dir = args.out_dir or DEFAULT_OUTPUT_ROOT / args.image.stem / "sam3"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_npz = args.out_dir / "mask.npz"
    out_preview = args.out_dir / "preview.png"
    out_meta = args.out_dir / "meta.json"

    sys.path.insert(0, str(args.sam3_dir))
    from sam3.model_builder import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    print("[SAM3] loading model from local checkpoint on cuda ...")
    model = build_sam3_image_model(
        checkpoint_path=str(args.checkpoint),
        load_from_HF=False,
        device="cuda",
        eval_mode=True,
    )
    # SAM3 has a known dtype-mismatch on newer GPUs:
    #   - vitdet uses sam3.perflib.fused.addmm_act, which hard-codes a
    #     bf16 cast on weight + activation
    #   - decoder.forward_ffn (decoder.py:79) wraps the FFN in
    #     `torch.amp.autocast(enabled=False)` -> FP32
    # Together they explode. Strategy: run the entire model in fp32 and
    # monkey-patch addmm_act with a plain F.linear so it does not force
    # a bf16 cast.
    import torch.nn as nn
    import torch.nn.functional as F

    def _safe_addmm_act(activation, linear, mat1):
        out = F.linear(mat1, linear.weight, linear.bias)
        if activation in (F.gelu, nn.GELU):
            out = F.gelu(out)
        elif activation in (F.relu, nn.ReLU):
            out = F.relu(out)
        return out

    sys.modules["sam3.perflib.fused"].addmm_act = _safe_addmm_act
    import sam3.model.vitdet as _vitdet_mod
    _vitdet_mod.addmm_act = _safe_addmm_act

    processor = Sam3Processor(model)

    pil_img = Image.open(args.image).convert("RGB")
    print(f"[SAM3] image: {pil_img.size}")

    with torch.inference_mode():
        state = processor.set_image(pil_img)
        out = processor.set_text_prompt(state=state, prompt=args.prompt)

    masks = out["masks"]
    boxes = out["boxes"]
    scores = out["scores"]

    masks_np = masks.cpu().numpy() if hasattr(masks, "cpu") else np.asarray(masks)
    boxes_np = boxes.cpu().numpy() if hasattr(boxes, "cpu") else np.asarray(boxes)
    scores_np = scores.cpu().numpy() if hasattr(scores, "cpu") else np.asarray(scores)

    if masks_np.ndim == 4:
        masks_np = masks_np[:, 0]
    elif masks_np.ndim == 3 and masks_np.shape[-1] == 1:
        masks_np = masks_np[..., 0]

    print(f"[SAM3] prompt='{args.prompt}' got {len(scores_np)} candidates")
    for i, s in enumerate(scores_np):
        print(f"  - candidate[{i}] score={float(s):.3f} box={boxes_np[i].tolist()}")

    best = int(np.argmax(scores_np))
    mask = masks_np[best] > 0

    np.savez(
        out_npz,
        mask=mask.astype(np.uint8),
        boxes=boxes_np,
        scores=scores_np,
        best_index=best,
        prompt=np.array(args.prompt),
    )
    print(f"[SAM3] wrote {out_npz}")

    rgb = np.array(pil_img)
    overlay = np.zeros_like(rgb)
    overlay[mask] = (0, 255, 0)
    viz = (0.5 * rgb + 0.5 * overlay).astype(np.uint8)
    Image.fromarray(viz).save(out_preview)
    print(f"[SAM3] wrote {out_preview}")

    with open(out_meta, "w") as f:
        json.dump({
            "image_size": list(pil_img.size),
            "prompt": args.prompt,
            "n_candidates": int(len(scores_np)),
            "scores": [float(s) for s in scores_np],
            "boxes": boxes_np.tolist(),
            "best_index": best,
            "best_score": float(scores_np[best]),
            "mask_pixels": int(mask.sum()),
            "mask_ratio": float(mask.mean()),
        }, f, indent=2)
    print(f"[SAM3] wrote {out_meta}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
