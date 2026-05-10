#!/usr/bin/env python3
"""
Sample ``Resolution.with_random_variation()`` for landscape / square / portrait.

For each orientation, draws *n* jittered resolutions (same base scale), aggregates
WxH frequencies, and prints rows sorted by total pixels then W×H. Each row includes
percent change versus the base aspect ratio (width/height) and versus base pixel count.

Run from repo root (or anywhere; cwd is normalized to project root).
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from sd_runner.resolution import Resolution  # noqa: E402
from utils.globals import ArchitectureType, ResolutionGroup  # noqa: E402


def _architecture(s: str) -> ArchitectureType:
    key = s.strip().upper().replace("-", "_")
    if key == "SD15":
        key = "SD_15"
    try:
        return ArchitectureType[key]
    except KeyError:
        choices = ", ".join(a.name for a in ArchitectureType)
        raise argparse.ArgumentTypeError(f"Unknown architecture '{s}'. Choices: {choices}")


def _resolution_group(s: str) -> ResolutionGroup:
    return ResolutionGroup.get(s.strip())


def _base_resolution(
    label: str,
    architecture_type: ArchitectureType,
    resolution_group: ResolutionGroup,
    scale: int,
) -> Resolution:
    if label == "landscape":
        return Resolution.LANDSCAPE(
            architecture_type,
            resolution_group=resolution_group,
            scale=scale,
        )
    if label == "square":
        return Resolution.SQUARE(
            architecture_type,
            resolution_group=resolution_group,
            scale=scale,
        )
    if label == "portrait":
        return Resolution.PORTRAIT(
            architecture_type,
            resolution_group=resolution_group,
            scale=scale,
        )
    raise ValueError(label)


def _run_group(
    label: str,
    architecture_type: ArchitectureType,
    resolution_group: ResolutionGroup,
    scale: int,
    *,
    variation_ratio: float,
    round_to: int,
    n: int,
) -> None:
    base = _base_resolution(label, architecture_type, resolution_group, scale)
    counter: Counter[tuple[int, int]] = Counter()

    for _ in range(n):
        out = base.with_random_variation(
            variation_ratio=variation_ratio, round_to=round_to
        )
        counter[(out.width, out.height)] += 1

    base_ar = float(base.width) / float(base.height) if base.height else 1.0
    base_px = base.width * base.height

    rows: list[tuple[int, int, int, int, float, float]] = []
    for (w, h), count in counter.items():
        px = w * h
        ar = float(w) / float(h) if h else 0.0
        pct_ar = 100.0 * (ar - base_ar) / base_ar if base_ar else 0.0
        pct_px = 100.0 * (px - base_px) / base_px if base_px else 0.0
        rows.append((px, w, h, count, pct_ar, pct_px))

    rows.sort(key=lambda t: (t[0], t[1], t[2]))

    print(f"\n=== {label.upper()} · base {base.width}×{base.height} "
          f"(scale={scale}) · {n} draws ===")
    hdr = (
        f"{'pixels':>11} {'W':>6} {'H':>6} "
        f"{'AR %+':>8} {'Px %+':>8} {'count':>6}  {'share':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for px, w, h, cnt, pct_ar, pct_px in rows:
        share = cnt / float(n)
        print(
            f"{px:11d} {w:>6} {h:>6} "
            f"{pct_ar:>7.2f}% {pct_px:>7.2f}% {cnt:>6}  {share:>7.2%}"
        )

    print(f"\nDistinct outcomes: {len(rows)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print distribution of with_random_variation() by orientation.",
    )
    parser.add_argument(
        "--architecture",
        type=str,
        default="SDXL",
        help="Architecture enum name, e.g. SDXL, SD_15, ILLUSTRIOUS, QWEN",
    )
    parser.add_argument(
        "--resolution-group",
        type=str,
        default="TEN_TWENTY_FOUR",
        help="Resolution group key or banner size, e.g. TEN_TWENTY_FOUR, 1024",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        help="Landscape/portrait/square scale index (matches tag digit, default 2).",
    )
    parser.add_argument(
        "--variation",
        type=float,
        default=0.05,
        help="with_random_variation variation_ratio",
    )
    parser.add_argument(
        "--round-to",
        type=int,
        default=16,
        help="snap multiple for sides",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=100,
        help="Monte Carlo draws per orientation",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="optional RNG seed for reproducibility",
    )
    args = parser.parse_args()

    if args.samples < 1:
        parser.error("--samples must be positive")

    if args.seed is not None:
        random.seed(args.seed)

    arch = _architecture(args.architecture)
    rg = _resolution_group(args.resolution_group)
    scale = args.scale

    print(
        "Dimension variation distribution preview\n"
        f"architecture={arch.name}, resolution_group={rg.name}, "
        f"variation={args.variation}, round_to={args.round_to}, "
        f"samples_per_orientation={args.samples}"
        + (f", seed={args.seed}" if args.seed is not None else "")
    )

    for label in ("landscape", "square", "portrait"):
        _run_group(
            label,
            arch,
            rg,
            scale,
            variation_ratio=args.variation,
            round_to=args.round_to,
            n=args.samples,
        )


if __name__ == "__main__":
    main()
