"""Filesystem-backed asset bundles and durable workflow state."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AssetRequest, AssetStatus, VALID_TRANSITIONS


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (value or "asset")[:40]


class AssetStore:
    """Owns the only writable generated-asset root for the workflow."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root.resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)

    def create(self, source_image: Path, request: AssetRequest) -> str:
        source_image = source_image.resolve()
        if not source_image.is_file():
            raise FileNotFoundError(source_image)
        shortid = hashlib.sha256(f"{_now()}:{source_image}:{request.prompt}".encode()).hexdigest()[:6]
        asset_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(request.asset_category or request.prompt)}-{shortid}"
        root = self.root(asset_id)
        if root.exists():
            raise FileExistsError(root)
        for name in ("input", "visual", "physics", "final"):
            (root / name).mkdir(parents=True)
        destination = root / "input" / f"source{source_image.suffix.lower() or '.image'}"
        shutil.copy2(source_image, destination)
        self.write_json(root / "request.json", request.to_dict())
        self.write_json(root / "input" / "metadata.json", {
            "source_filename": source_image.name,
            "copied_path": self.relative(asset_id, destination),
            "sha256": self._sha256(destination),
            "created_at": _now(),
        })
        manifest = {
            "schema_version": 2,
            "asset_id": asset_id,
            "created_at": _now(),
            "updated_at": _now(),
            "status": AssetStatus.CREATED.value,
            "source_image": self.relative(asset_id, destination),
            "artifacts": {},
            "events": [{"at": _now(), "status": AssetStatus.CREATED.value, "message": "Asset bundle created"}],
            "error": None,
        }
        self.write_json(root / "manifest.json", manifest)
        return asset_id

    def root(self, asset_id: str) -> Path:
        if Path(asset_id).name != asset_id or not asset_id:
            raise ValueError("asset_id must be a directory name")
        root = (self.output_root / asset_id).resolve()
        if self.output_root not in root.parents:
            raise ValueError("asset path escapes output root")
        return root

    def manifest(self, asset_id: str) -> dict[str, Any]:
        return self.read_json(self.root(asset_id) / "manifest.json")

    def transition(self, asset_id: str, target: AssetStatus, message: str) -> dict[str, Any]:
        manifest = self.manifest(asset_id)
        current = AssetStatus(manifest["status"])
        if target not in VALID_TRANSITIONS[current]:
            raise ValueError(f"Illegal status transition: {current.value} -> {target.value}")
        manifest["status"] = target.value
        manifest["updated_at"] = _now()
        manifest["events"].append({"at": _now(), "status": target.value, "message": message})
        if target != AssetStatus.FAILED:
            manifest["error"] = None
        self.write_json(self.root(asset_id) / "manifest.json", manifest)
        return manifest

    def fail(self, asset_id: str, message: str) -> dict[str, Any]:
        manifest = self.manifest(asset_id)
        current = AssetStatus(manifest["status"])
        if current != AssetStatus.FAILED:
            self.transition(asset_id, AssetStatus.FAILED, message)
            manifest = self.manifest(asset_id)
        manifest["error"] = message
        manifest["updated_at"] = _now()
        self.write_json(self.root(asset_id) / "manifest.json", manifest)
        return manifest

    def set_artifact(self, asset_id: str, name: str, path: Path) -> None:
        manifest = self.manifest(asset_id)
        manifest["artifacts"][name] = self.relative(asset_id, path)
        manifest["updated_at"] = _now()
        self.write_json(self.root(asset_id) / "manifest.json", manifest)

    def relative(self, asset_id: str, path: Path) -> str:
        path = path.resolve()
        root = self.root(asset_id)
        if path != root and root not in path.parents:
            raise ValueError(f"Path is outside asset root: {path}")
        return path.relative_to(root).as_posix()

    @staticmethod
    def write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
