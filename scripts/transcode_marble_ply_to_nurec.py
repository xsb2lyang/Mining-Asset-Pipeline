#!/usr/bin/env python3
"""Transcode Marble Gaussian PLY files to the NuRec layout Isaac Sim expects.

Marble's downloadable PLY exports commonly contain only the three DC colour
coefficients (``f_dc_*``).  Current 3dgrut correctly represents that as an
empty high-order SH tensor, but the NuRec renderer used by Isaac Sim 5.1 does
not reliably render an empty tensor.  The historical WorldComposer exporter
instead wrote a degree-3, zero-filled SH tensor.  This small compatibility
adapter preserves the PLY's actual geometry and DC colour while restoring that
renderer-compatible layout.

Run this script in the isolated ``worldcomposer-r2s`` environment created by
``scripts/setup_scene_phase1_env.sh``.  It deliberately has no Isaac Sim or
World Labs dependency.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path


COMPATIBILITY_SH_DEGREE = 3


def _expected_specular_width(sh_degree: int) -> int:
    """Return the flattened RGB width for all non-DC SH coefficients."""
    if sh_degree < 0:
        raise ValueError("SH degree must be non-negative")
    return ((sh_degree + 1) ** 2 - 1) * 3


def _pad_specular_for_nurec(attrs, sh_degree: int):
    """Return attributes whose SH tensor satisfies the legacy NuRec contract."""
    import numpy as np

    target_width = _expected_specular_width(sh_degree)
    current_width = int(attrs.specular.shape[1])
    if current_width > target_width:
        raise ValueError(
            f"PLY has {current_width} higher-order SH values per Gaussian, which exceeds "
            f"the compatibility degree-{sh_degree} layout ({target_width})"
        )
    if current_width == target_width:
        return attrs, False
    padded = np.zeros((attrs.num_gaussians, target_width), dtype=np.float32)
    if current_width:
        padded[:, :current_width] = attrs.specular
    return replace(attrs, specular=padded), True


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Marble Gaussian PLY to a fixed-SH NuRec USDZ compatible with Isaac Sim 5.1."
    )
    parser.add_argument("--ply", type=Path, required=True, help="Input binary Gaussian PLY")
    parser.add_argument("--output", type=Path, required=True, help="Output .usdz path")
    parser.add_argument(
        "--sh-degree",
        type=int,
        default=COMPATIBILITY_SH_DEGREE,
        help="NuRec SH degree to author (default: 3; required by the legacy renderer)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    ply = args.ply.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not ply.is_file() or ply.suffix.lower() != ".ply":
        raise ValueError(f"--ply must be an existing .ply file: {ply}")
    if output.suffix.lower() != ".usdz":
        raise ValueError(f"--output must use the .usdz extension: {output}")
    if args.sh_degree != COMPATIBILITY_SH_DEGREE:
        raise ValueError(
            f"Only compatibility SH degree {COMPATIBILITY_SH_DEGREE} is supported; got {args.sh_degree}"
        )

    # Imports stay here so ``--help`` and repository unit tests do not require
    # the heavyweight isolated 3dgrut environment.
    from threedgrut.export.adapter import AttributesExportAdapter
    from threedgrut.export.importers.ply import PLYImporter
    from threedgrut.export.usd.nurec.exporter import NuRecExporter

    attrs, capabilities = PLYImporter(max_sh_degree=args.sh_degree).load(ply)
    attrs, padded = _pad_specular_for_nurec(attrs, args.sh_degree)
    capabilities = replace(capabilities, sh_degree=args.sh_degree)
    adapter = AttributesExportAdapter(attrs, capabilities, is_preactivation=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    NuRecExporter(export_cameras=False).export(adapter, output)
    print(
        f"nurec_usdz={output}\n"
        f"gaussians={attrs.num_gaussians}\n"
        f"sh_degree={args.sh_degree}\n"
        f"zero_padded_higher_order_sh={str(padded).lower()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
