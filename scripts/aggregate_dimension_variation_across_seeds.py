#!/usr/bin/env python3
"""
Run the same Monte Carlo as ``sample_dimension_variation_distribution.py`` for many
RNG seeds, then summarize how often specific WxH outcomes appear (default: 1024x1024).

Uses ``sample_orientation_counts()`` from the sibling script (same parameters).

Run from repo root:

    python scripts/aggregate_dimension_variation_across_seeds.py --num-seeds 1000
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import random
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)


def _load_sample_module():
    path = os.path.join(os.path.dirname(__file__), "sample_dimension_variation_distribution.py")
    spec = importlib.util.spec_from_file_location("sample_dimension_variation_distribution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sdv = _load_sample_module()
_architecture = _sdv._architecture
_resolution_group = _sdv._resolution_group
sample_orientation_counts = _sdv.sample_orientation_counts


def _parse_dim(s: str) -> tuple[int, int]:
    s = s.strip().lower().replace(" ", "")
    if "x" not in s:
        raise argparse.ArgumentTypeError(
            f"Dimension must look like 1024x1024, got {s!r}"
        )
    a, b = s.split("x", 1)
    return int(a), int(b)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate with_random_variation() outcomes over many seeds; "
            "report frequency of target dimensions."
        ),
    )
    parser.add_argument(
        "--architecture",
        type=str,
        default="SDXL",
        help="Architecture enum name (same as sample_dimension_variation_distribution.py)",
    )
    parser.add_argument(
        "--resolution-group",
        type=str,
        default="TEN_TWENTY_FOUR",
        help="Resolution group key (same as sibling script)",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        help="Landscape / square / portrait scale index",
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
        help="Snap multiple for sides",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=100,
        help="Monte Carlo draws per orientation per seed",
    )
    parser.add_argument(
        "--num-seeds",
        type=int,
        default=1000,
        help="Number of seeds: 0, 1, …, num_seeds-1",
    )
    parser.add_argument(
        "--seed-start",
        type=int,
        default=0,
        help="First seed (inclusive); seeds are seed_start .. seed_start+num_seeds-1",
    )
    parser.add_argument(
        "--target-dim",
        type=_parse_dim,
        action="append",
        dest="target_dims",
        metavar="WxH",
        help=(
            "Track this width x height (repeat flag for multiple). "
            "Default if omitted: 1024x1024"
        ),
    )
    parser.add_argument(
        "--orientations",
        type=str,
        default="landscape,square,portrait",
        help="Comma-separated subset of landscape,square,portrait",
    )
    args = parser.parse_args()

    if args.samples < 1:
        parser.error("--samples must be positive")
    if args.num_seeds < 1:
        parser.error("--num-seeds must be positive")

    target_dims: list[tuple[int, int]] = (
        args.target_dims if args.target_dims is not None and len(args.target_dims) > 0 else [(1024, 1024)]
    )
    target_set = frozenset(target_dims)

    orientations = [x.strip().lower() for x in args.orientations.split(",") if x.strip()]
    allowed = {"landscape", "square", "portrait"}
    bad = [o for o in orientations if o not in allowed]
    if bad:
        parser.error(f"Unknown orientation(s): {bad}. Use: {', '.join(sorted(allowed))}")

    arch = _architecture(args.architecture)
    rg = _resolution_group(args.resolution_group)
    scale = args.scale

    # Per orientation: total counts for each target + other (not in target_set)
    per_label: dict[str, Counter[tuple[int, int] | str]] = {
        label: Counter() for label in orientations
    }
    combined: Counter[tuple[int, int] | str] = Counter()

    for seed in range(args.seed_start, args.seed_start + args.num_seeds):
        random.seed(seed)
        for label in orientations:
            counter, _base = sample_orientation_counts(
                label,
                arch,
                rg,
                scale,
                variation_ratio=args.variation,
                round_to=args.round_to,
                n=args.samples,
            )
            other = 0
            for (w, h), c in counter.items():
                if (w, h) in target_set:
                    per_label[label][(w, h)] += c
                    combined[(w, h)] += c
                else:
                    other += c
            per_label[label]["__other__"] += other
            combined["__other__"] += other

    total_draws = args.num_seeds * args.samples * len(orientations)
    print(
        "Aggregated dimension hits across seeds\n"
        f"architecture={arch.name}, resolution_group={rg.name}, scale={scale}, "
        f"variation={args.variation}, round_to={args.round_to}\n"
        f"seeds={args.seed_start}..{args.seed_start + args.num_seeds - 1} "
        f"({args.num_seeds} seeds), samples_per_orientation_per_seed={args.samples}, "
        f"orientations={orientations}\n"
        f"target dimensions: {', '.join(f'{w}x{h}' for w, h in target_dims)}\n"
        f"total random draws = seeds * samples * orientations = {total_draws}"
    )

    def _print_block(title: str, ctr: Counter[tuple[int, int] | str], draws: int) -> None:
        print(f"\n=== {title} -- {draws} draws ===")
        rows: list[tuple[str, int, float]] = []
        for key in target_dims:
            cnt = int(ctr[key])
            rows.append((f"{key[0]}x{key[1]}", cnt, cnt / draws if draws else 0.0))
        ocnt = int(ctr["__other__"])
        rows.append(("other (not in target set)", ocnt, ocnt / draws if draws else 0.0))
        hdr = f"{'bucket':<28} {'count':>10} {'share':>10}"
        print(hdr)
        print("-" * len(hdr))
        for name, cnt, share in rows:
            print(f"{name:<28} {cnt:10d} {share:9.4%}")

    per_draws = args.num_seeds * args.samples
    for label in orientations:
        _print_block(label.upper(), per_label[label], per_draws)
    _print_block("ALL ORIENTATIONS COMBINED", combined, total_draws)


if __name__ == "__main__":
    main()
