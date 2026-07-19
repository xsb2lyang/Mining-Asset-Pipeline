#!/usr/bin/env python3
"""Generate a Marble world from an RGB image or an orbit video.

This optional acquisition step is deliberately separate from
``run_scene_phase1.py``: users may instead supply PLY/GLB exports made on a
different machine. Credentials are read only from ``WORLDLABS_API_KEY``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://api.worldlabs.ai/marble/v1"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv"}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Marble world from an image or video and download PLY + collider GLB."
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--image", type=Path, help="Single RGB source image")
    source_group.add_argument(
        "--video",
        type=Path,
        help="Orbit/camera-motion source video (.mp4, .mov, or .mkv)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "local_data" / "scene_inputs" / "marble",
    )
    parser.add_argument("--display-name", default="Mining Scene")
    parser.add_argument(
        "--prompt",
        help="Optional text guidance; Marble captions the source automatically when omitted",
    )
    parser.add_argument("--model", default="marble-1.1-plus")
    parser.add_argument(
        "--ply-resolution",
        choices=("full_res", "500k", "150k", "100k"),
        default="full_res",
    )
    parser.add_argument("--export-hq-mesh", action="store_true")
    parser.add_argument("--poll-interval", type=float, default=20.0)
    parser.add_argument("--operation-timeout", type=float, default=7200.0)
    return parser.parse_args(argv)


def _source_from_args(args: argparse.Namespace) -> tuple[Path, str]:
    """Return the local source file and Marble media kind."""
    source = (args.video or args.image).expanduser().resolve()
    kind = "video" if args.video else "image"
    if not source.is_file():
        raise FileNotFoundError(f"{kind.capitalize()} not found: {source}")
    if kind == "video" and source.suffix.lower() not in VIDEO_SUFFIXES:
        supported = ", ".join(sorted(VIDEO_SUFFIXES))
        raise ValueError(f"Video must use one of: {supported}")
    return source, kind


def _media_asset_id(upload: dict[str, Any]) -> str:
    """Accept both documented and legacy media-asset ID response shapes."""
    media_asset = upload.get("media_asset", {})
    identifier = media_asset.get("id") or media_asset.get("media_asset_id")
    if not isinstance(identifier, str) or not identifier:
        raise RuntimeError("Marble upload response does not contain a media asset ID")
    return identifier


def _world_prompt(kind: str, media_asset_id: str, text_prompt: str | None) -> dict[str, Any]:
    prompt: dict[str, Any] = {
        "type": kind,
        f"{kind}_prompt": {
            "source": "media_asset",
            "media_asset_id": media_asset_id,
        },
    }
    if text_prompt and text_prompt.strip():
        prompt["text_prompt"] = text_prompt.strip()
    return prompt


def _wait_for_operation(
    session: Any,
    operation: dict[str, Any],
    *,
    auth_headers: dict[str, str],
    label: str,
    poll_interval: float,
    timeout: float,
) -> dict[str, Any]:
    operation_id = operation["operation_id"]
    deadline = time.monotonic() + timeout
    current = operation
    while not current.get("done"):
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{label} timed out after {timeout:.0f}s")
        time.sleep(poll_interval)
        response = session.get(
            f"{BASE_URL}/operations/{operation_id}",
            headers=auth_headers,
            timeout=60,
        )
        response.raise_for_status()
        current = response.json()
        progress = current.get("metadata", {}).get("progress", {})
        print(f"{label}: {progress.get('status')} - {progress.get('description')}", flush=True)
    if current.get("error"):
        raise RuntimeError(f"{label} failed: {current['error']}")
    payload = current.get("response")
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} completed without a response object")
    return payload


def _download(session: Any, url: str, destination: Path) -> None:
    response = session.get(url, timeout=600, stream=True)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as stream:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                stream.write(chunk)


def _export(
    session: Any,
    *,
    world_id: str,
    payload: dict[str, Any],
    destination: Path,
    headers: dict[str, str],
    auth_headers: dict[str, str],
    args: argparse.Namespace,
    label: str,
) -> None:
    response = session.post(
        f"{BASE_URL}/worlds/{world_id}:export",
        headers=headers,
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    result = _wait_for_operation(
        session,
        response.json(),
        auth_headers=auth_headers,
        label=label,
        poll_interval=args.poll_interval,
        timeout=args.operation_timeout,
    )
    url = result.get("url")
    if not isinstance(url, str) or not url:
        raise RuntimeError(f"{label} completed without a download URL")
    _download(session, url, destination)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api_key = os.environ.get("WORLDLABS_API_KEY")
    if not api_key:
        print("WORLDLABS_API_KEY is not set", file=sys.stderr)
        return 2
    try:
        source, source_kind = _source_from_args(args)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        import requests
    except ImportError:
        print("Install the optional scene client: pip install -e '.[scene]'", file=sys.stderr)
        return 2

    headers = {"WLT-Api-Key": api_key, "Content-Type": "application/json"}
    auth_headers = {"WLT-Api-Key": api_key}
    session = requests.Session()
    try:
        prepare = session.post(
            f"{BASE_URL}/media-assets:prepare_upload",
            headers=headers,
            json={
                "file_name": source.name,
                "kind": source_kind,
                "extension": source.suffix.lower().lstrip("."),
            },
            timeout=60,
        )
        prepare.raise_for_status()
        upload = prepare.json()
        media_asset_id = _media_asset_id(upload)
        with source.open("rb") as stream:
            uploaded = session.put(
                upload["upload_info"]["upload_url"],
                headers=upload["upload_info"]["required_headers"],
                data=stream,
                timeout=300,
            )
        uploaded.raise_for_status()

        generated = session.post(
            f"{BASE_URL}/worlds:generate",
            headers=headers,
            json={
                "display_name": args.display_name,
                "model": args.model,
                "world_prompt": _world_prompt(source_kind, media_asset_id, args.prompt),
            },
            timeout=60,
        )
        generated.raise_for_status()
        operation = generated.json()
        world = _wait_for_operation(
            session,
            operation,
            auth_headers=auth_headers,
            label="Marble world generation",
            poll_interval=args.poll_interval,
            timeout=args.operation_timeout,
        )
        marble_url = world.get("world_marble_url", "")
        world_id = (
            marble_url.rstrip("/").rsplit("/", 1)[-1]
            if isinstance(marble_url, str) and marble_url
            else world.get("world_id") or world.get("id") or operation["operation_id"]
        )
        output = args.output_root.expanduser().resolve() / str(world_id)
        output.mkdir(parents=True, exist_ok=False)

        assets = world.get("assets", {})
        collider_url = assets.get("mesh", {}).get("collider_mesh_url")
        if not collider_url:
            raise RuntimeError("Marble response does not contain collider_mesh_url")
        _download(session, collider_url, output / "collider.glb")
        for filename, url in (
            ("thumbnail.webp", assets.get("thumbnail_url")),
            ("pano.png", assets.get("imagery", {}).get("pano_url")),
        ):
            if url:
                _download(session, url, output / filename)

        _export(
            session,
            world_id=str(world_id),
            payload={
                "asset_type": "splats",
                "format": "ply",
                "resolution": args.ply_resolution,
            },
            destination=output / "scene.ply",
            headers=headers,
            auth_headers=auth_headers,
            args=args,
            label="PLY export",
        )
        if args.export_hq_mesh:
            _export(
                session,
                world_id=str(world_id),
                payload={"asset_type": "mesh", "format": "glb", "mesh_variant": "textured"},
                destination=output / "textured_mesh.glb",
                headers=headers,
                auth_headers=auth_headers,
                args=args,
                label="Textured mesh export",
            )

        manifest = {
            "schema_version": 2,
            "provider": "world_labs_marble",
            "world_id": str(world_id),
            "operation_id": operation["operation_id"],
            "model": args.model,
            "display_name": args.display_name,
            "source": {"kind": source_kind, "path": str(source)},
            "prompt": args.prompt.strip() if args.prompt and args.prompt.strip() else None,
            "ply_resolution": args.ply_resolution,
            "artifacts": {"ply": "scene.ply", "collider_glb": "collider.glb"},
        }
        (output / "marble_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 - normalize API/client failures.
        print(f"Marble generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"world_id={world_id}")
    print(f"phase1_ply={output / 'scene.ply'}")
    print(f"phase1_glb={output / 'collider.glb'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
