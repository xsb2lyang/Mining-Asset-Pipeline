"""Filesystem-backed asset bundles and durable workflow state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import AssetPhase, AssetQuality, AssetRequest, AssetStatus, VALID_TRANSITIONS


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

    def create(
        self,
        source_image: Path,
        request: AssetRequest,
        *,
        controller: str = "external_skill",
        max_llm_calls: int = 0,
    ) -> str:
        source_image = source_image.resolve()
        if not source_image.is_file():
            raise FileNotFoundError(source_image)
        shortid = uuid.uuid4().hex[:6]
        asset_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(request.asset_category or request.prompt)}-{shortid}"
        root = self.root(asset_id)
        if root.exists():
            raise FileExistsError(root)
        if controller not in {"external_skill", "embedded_claude_api"}:
            raise ValueError("unsupported controller")
        if max_llm_calls < 0:
            raise ValueError("max_llm_calls cannot be negative")
        for name in (
            "input", "agent/decisions", "visual/sam3_attempts", "visual/sam3d_attempts",
            "physics/author", "physics/critic", "physics/logs", "final",
        ):
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
            "schema_version": 3,
            "asset_id": asset_id,
            "created_at": _now(),
            "updated_at": _now(),
            "status": AssetStatus.CREATED.value,
            "phase": AssetPhase.INPUT_ANALYSIS.value,
            "quality": AssetQuality.PENDING.value,
            "controller": controller,
            "budget": {"max_llm_calls": max_llm_calls, "llm_calls_used": 0},
            "attempts": {"sam3": 0, "sam3d": 0, "physics": 0},
            "source_image": self.relative(asset_id, destination),
            "source_sha256": self._sha256(destination),
            "source_size": destination.stat().st_size,
            "artifacts": {},
            "artifact_hashes": {},
            "artifact_sizes": {},
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

    def transition(
        self,
        asset_id: str,
        target: AssetStatus,
        message: str,
        *,
        phase: AssetPhase | str | None = None,
        quality: AssetQuality | str | None = None,
    ) -> dict[str, Any]:
        manifest = self.manifest(asset_id)
        self.require_v3(manifest)
        current = AssetStatus(manifest["status"])
        if target not in VALID_TRANSITIONS[current]:
            raise ValueError(f"Illegal status transition: {current.value} -> {target.value}")
        manifest["status"] = target.value
        if phase is not None:
            manifest["phase"] = phase.value if isinstance(phase, AssetPhase) else AssetPhase(phase).value
        if quality is not None:
            manifest["quality"] = quality.value if isinstance(quality, AssetQuality) else AssetQuality(quality).value
        manifest["updated_at"] = _now()
        manifest["events"].append({"at": _now(), "status": target.value, "message": message})
        if target != AssetStatus.FAILED:
            manifest["error"] = None
        self.write_json(self.root(asset_id) / "manifest.json", manifest)
        return manifest

    def fail(self, asset_id: str, message: str) -> dict[str, Any]:
        manifest = self.manifest(asset_id)
        self.require_v3(manifest)
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
        self.require_v3(manifest)
        manifest["artifacts"][name] = self.relative(asset_id, path)
        if path.is_file():
            manifest.setdefault("artifact_hashes", {})[name] = self._sha256(path)
            manifest.setdefault("artifact_sizes", {})[name] = path.stat().st_size
        manifest["updated_at"] = _now()
        self.write_json(self.root(asset_id) / "manifest.json", manifest)

    def set_phase(self, asset_id: str, phase: AssetPhase | str, message: str) -> dict[str, Any]:
        manifest = self.manifest(asset_id)
        self.require_v3(manifest)
        if AssetStatus(manifest["status"]) not in {AssetStatus.CREATED, AssetStatus.RUNNING}:
            raise ValueError(f"Cannot change phase while status is {manifest['status']}; resume the asset first")
        target = phase.value if isinstance(phase, AssetPhase) else AssetPhase(phase).value
        manifest["status"] = AssetStatus.RUNNING.value
        manifest["phase"] = target
        manifest["updated_at"] = _now()
        manifest["events"].append({"at": _now(), "status": AssetStatus.RUNNING.value, "phase": target, "message": message})
        manifest["error"] = None
        self.write_json(self.root(asset_id) / "manifest.json", manifest)
        return manifest

    def increment(self, asset_id: str, group: str, name: str, amount: int = 1) -> int:
        manifest = self.manifest(asset_id)
        self.require_v3(manifest)
        bucket = manifest.setdefault(group, {})
        bucket[name] = int(bucket.get(name, 0)) + amount
        manifest["updated_at"] = _now()
        self.write_json(self.root(asset_id) / "manifest.json", manifest)
        return int(bucket[name])

    def append_trace(self, asset_id: str, event: dict[str, Any]) -> None:
        self.require_v3(self.manifest(asset_id))
        path = self.root(asset_id) / "agent" / "trace.jsonl"
        payload = {"at": _now(), **event}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @staticmethod
    def require_v3(manifest: dict[str, Any]) -> None:
        if manifest.get("schema_version") != 3:
            raise ValueError("schema v2 assets are read-only and cannot be resumed or modified")

    def relative(self, asset_id: str, path: Path) -> str:
        path = path.resolve()
        root = self.root(asset_id)
        if path != root and root not in path.parents:
            raise ValueError(f"Path is outside asset root: {path}")
        return path.relative_to(root).as_posix()

    def resolve_relative(self, asset_id: str, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError("artifact path must be a non-empty relative path")
        root = self.root(asset_id)
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise ValueError("artifact path escapes asset root")
        return path

    def artifact_path(self, asset_id: str, name: str, *, verify_hash: bool = True) -> Path:
        manifest = self.manifest(asset_id)
        relative = manifest.get("artifacts", {}).get(name)
        if not relative:
            raise ValueError(f"required artifact is missing: {name}")
        path = self.resolve_relative(asset_id, relative)
        if not path.is_file():
            raise FileNotFoundError(path)
        expected = manifest.get("artifact_hashes", {}).get(name)
        if verify_hash and expected and self._sha256(path) != expected:
            raise ValueError(f"artifact hash mismatch: {name}")
        return path

    def source_path(self, asset_id: str, *, verify_hash: bool = True) -> Path:
        """Return the copied RGB input and reject modified resume inputs."""
        manifest = self.manifest(asset_id)
        self.require_v3(manifest)
        path = self.resolve_relative(asset_id, manifest.get("source_image", ""))
        if not path.is_file():
            raise FileNotFoundError(path)
        metadata_path = self.root(asset_id) / "input" / "metadata.json"
        metadata = self.read_json(metadata_path)
        if metadata.get("copied_path") != manifest.get("source_image"):
            raise ValueError("source image metadata does not match the manifest")
        expected = manifest.get("source_sha256")
        if expected != metadata.get("sha256"):
            raise ValueError("source image hash metadata does not match the manifest")
        if verify_hash and (not isinstance(expected, str) or self._sha256(path) != expected):
            raise ValueError("source image hash mismatch")
        return path

    @staticmethod
    def write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

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
