"""Deterministic checks for SAM3 masks and GLB mesh integrity."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def inspect_sam3(npz_path: Path, meta_path: Path) -> dict[str, Any]:
    data = np.load(npz_path, allow_pickle=False)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    mask = data["mask"].astype(bool)
    scores = np.asarray(data["scores"], dtype=float)
    boxes = np.asarray(data["boxes"], dtype=float)
    issues: list[str] = []
    if scores.size == 0:
        issues.append("no_candidates")
    if scores.size and float(scores.max()) < 0.5:
        issues.append("low_confidence")
    ratio = float(mask.mean()) if mask.size else 0.0
    if ratio < 0.005:
        issues.append("mask_too_small")
    if ratio > 0.95:
        issues.append("mask_too_large")
    if boxes.ndim != 2 or boxes.shape[-1] != 4 or not np.isfinite(boxes).all():
        issues.append("invalid_boxes")
    selected = int(data["selected_index"]) if "selected_index" in data else int(data["best_index"])
    candidate_masks = data["candidate_masks"].astype(bool) if "candidate_masks" in data else None
    recommended = None
    if candidate_masks is not None and candidate_masks.ndim >= 3:
        for index, candidate in enumerate(candidate_masks):
            candidate_ratio = float(candidate.mean())
            if index < scores.size and scores[index] >= 0.5 and 0.005 <= candidate_ratio <= 0.95:
                recommended = index
                break
    return {
        "status": "pass" if not issues else "needs_review",
        "issues": issues,
        "candidate_count": int(scores.size),
        "selected_index": selected,
        "best_score": float(scores[selected]) if scores.size > selected >= 0 else None,
        "mask_ratio": ratio,
        "mask_pixels": int(mask.sum()),
        "image_size": meta.get("image_size"),
        "recommended_candidate_index": recommended if recommended != selected else None,
    }


def select_sam3_candidate(npz_path: Path, meta_path: Path, image_path: Path, index: int) -> None:
    """Select a previously generated candidate without re-running SAM3."""
    with np.load(npz_path, allow_pickle=False) as data:
        values = {name: data[name] for name in data.files}
    candidates = values.get("candidate_masks")
    if candidates is None or index < 0 or index >= len(candidates):
        raise ValueError("Requested SAM3 candidate is unavailable")
    mask = candidates[index].astype(np.uint8)
    values["mask"] = mask
    values["selected_index"] = np.array(index)
    values["best_index"] = np.array(index)
    np.savez(npz_path, **values)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["selected_index"] = index
    meta["best_index"] = index
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    rgb = np.array(Image.open(image_path).convert("RGB"))
    overlay = np.zeros_like(rgb)
    overlay[mask.astype(bool)] = (0, 255, 0)
    Image.fromarray((0.5 * rgb + 0.5 * overlay).astype(np.uint8)).save(npz_path.parent / "preview.png")


def inspect_glb(path: Path) -> dict[str, Any]:
    """Read GLB structure without requiring a renderer or trimesh dependency."""
    issues: list[str] = []
    warnings: list[str] = []
    if not path.is_file() or path.stat().st_size < 64:
        return {"status": "needs_review", "issues": ["missing_or_empty_glb"], "warnings": []}
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12:
            return {"status": "needs_review", "issues": ["invalid_glb_header"], "warnings": []}
        magic, version, total_length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or total_length > path.stat().st_size:
            return {"status": "needs_review", "issues": ["invalid_glb_header"], "warnings": []}
        chunk_header = handle.read(8)
        if len(chunk_header) != 8:
            return {"status": "needs_review", "issues": ["missing_glb_json"], "warnings": []}
        chunk_length, chunk_type = struct.unpack("<I4s", chunk_header)
        if chunk_type != b"JSON":
            return {"status": "needs_review", "issues": ["missing_glb_json"], "warnings": []}
        try:
            document = json.loads(handle.read(chunk_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"status": "needs_review", "issues": ["invalid_glb_json"], "warnings": []}
    accessors = document.get("accessors", [])
    primitives = [primitive for mesh in document.get("meshes", []) for primitive in mesh.get("primitives", [])]
    vertex_count = 0
    face_count = 0
    has_color = False
    for primitive in primitives:
        position = primitive.get("attributes", {}).get("POSITION")
        if not isinstance(position, int) or position >= len(accessors):
            issues.append("missing_positions")
            continue
        vertex_count += int(accessors[position].get("count", 0))
        indices = primitive.get("indices")
        if isinstance(indices, int) and indices < len(accessors):
            face_count += int(accessors[indices].get("count", 0)) // 3
        has_color = has_color or "COLOR_0" in primitive.get("attributes", {})
    if not primitives or vertex_count == 0 or face_count == 0:
        issues.append("empty_mesh")
    if not has_color and not document.get("materials"):
        warnings.append("no_vertex_color_or_material")
    return {
        "status": "pass" if not issues else "needs_review",
        "issues": sorted(set(issues)),
        "warnings": warnings,
        "mesh_primitive_count": len(primitives),
        "vertex_count": vertex_count,
        "face_count": face_count,
        "has_vertex_color": has_color,
        "file_size_bytes": path.stat().st_size,
    }
