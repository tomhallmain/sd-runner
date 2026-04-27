#!/usr/bin/env python3
"""
Compare concepts from an external wildcards directory (e.g. sd-wildcards) against
concepts already present in this repository's concept files.

Now includes:
  - WILDCARD_TO_TARGET: maps each wildcard filename stem to a target repo file
    (existing or planned with category-prefix naming convention)
  - Per-line blacklist filtering of missing concepts
  - --export-dir: writes importable missing concepts grouped by target file,
    ready to feed into ConceptEditorWindow's Import button

Run from the repository root:

    python scripts/compare_and_merge_wildcards_with_repo_concepts.py
    python scripts/compare_and_merge_wildcards_with_repo_concepts.py --csv wildcard_coverage.csv
    python scripts/compare_and_merge_wildcards_with_repo_concepts.py --export-dir
    python scripts/compare_and_merge_wildcards_with_repo_concepts.py --include-dictionary

Uses the same line parsing as ``Concepts.load`` (strip, stop at ``#``).
Matching is case-insensitive unless ``--case-sensitive`` is passed.
By default, NSFW wildcard files are skipped and only SFW + Art Styles repo
concepts are included in the coverage check.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Wildcard → target-repo-file mapping
#
# Keys are wildcard filename stems (no extension).
# Values:
#   str   — target filename inside the concepts dir (may not exist yet)
#   "skip"— explicitly excluded; shown in a compact skip summary only
#   None  — unmapped / needs manual review; shown separately
#
# Files whose stems appear in is_nsfw_wildcard_file() are suppressed before
# this table is consulted, so they don't need "skip" entries here unless you
# want to be explicit.
#
# New files follow the category-prefix convention:
#   objects_*.txt, plants_*.txt  — belong to the "objects"/"plants" UI category
# ---------------------------------------------------------------------------
WILDCARD_TO_TARGET: dict[str, str | None] = {
    # ── media_features.txt ──────────────────────────────────────────────────
    "3d-term":            "media_features.txt",   # 3D/rendering terms
    "adj-architecture":   "media_features.txt",   # architectural style adjectives
    "aspect-ratio":       "media_features.txt",   # technical prompt syntax
    "background":         "media_features.txt",   # visual bg type (not a place)
    "camera":             "media_features.txt",   # camera models
    "camera-manu":        "media_features.txt",   # brand names only
    "detail":             "media_features.txt",   # detail-level modifiers
    "f-stop":             "media_features.txt",   # technical camera setting
    "fantasy":            "media_features.txt",   # fantastical art style tags
    "film-genre":         "media_features.txt",   # film genres as style tags
    "focal-length":       "media_features.txt",   # technical camera setting
    "gen-modifier":       "media_features.txt",   # general prompt modifiers
    "genre":              "media_features.txt",   # genre style tags
    "hd":                 "media_features.txt",   # HD / resolution qualifiers
    "iso-stop":           "media_features.txt",   # technical camera setting
    "landscape":          "locations.txt",
    "movement":           "media_features.txt",   # art movements (impressionism, etc.)
    "oil-painting":       "media_features.txt",   # oil painting styles
    "photo-term":         "media_features.txt",   # photography terminology
    "portrait-type":      "media_features.txt",   # portrait framing types
    "render":             "media_features.txt",   # render style tags
    "render-engine":      "media_features.txt",   # render engine names
    "scifi":              "media_features.txt",   # sci-fi visual aesthetic tags
    "sculpture":          "media_features.txt",
    "style":              "media_features.txt",   # general visual style tags
    "technique":          "media_features.txt",   # artistic technique tags
    "watercolor":         "media_features.txt",   # watercolour style tags
    "wave":               "media_features.txt",   # ambiguous

    # ── lighting.txt (existing) ─────────────────────────────────────────────
    "lighting":           "lighting.txt",

    # ── object.txt (existing) ───────────────────────────────────────────────
    "game":               "object.txt",
    "gem":                "object.txt",
    "noun-general":       "object.txt",    # large; review before bulk import
    "ship":               "object.txt",
    "still-life":         "object.txt",
    "train":              "object.txt",
    "water":              "object.txt",

    # ── objects_cosmic.txt (new) ─────────────────────────────────────────────
    "cosmic-galaxy":      "objects_cosmic.txt",
    "cosmic-nebula":      "objects_cosmic.txt",
    "cosmic-star":        "objects_cosmic.txt",
    "cosmic-term":        "objects_cosmic.txt",
    "planet":             "objects_cosmic.txt",

    # ── objects_food.txt (new) ───────────────────────────────────────────────
    "food":               "objects_food.txt",
    "fruit":              "objects_food.txt",

    # ── objects_furniture.txt (new) ──────────────────────────────────────────
    "furniture":          "objects_furniture.txt",

    # ── objects_rpg.txt (new) ────────────────────────────────────────────────
    "rpg-Item":           "objects_rpg.txt",

    # ── objects_scifi.txt (new) ──────────────────────────────────────────────
    "noun-scifi":         "objects_scifi.txt",
    "robot":              "objects_scifi.txt",

    # ── plants.txt (existing) ────────────────────────────────────────────────
    "biome":              "plants.txt",
    "flower":             "plants.txt",
    "forest-type":        "plants.txt",
    "tree":               "plants.txt",

    # ── animals.txt (existing) ───────────────────────────────────────────────
    "animal":             "animals.txt",
    "bird":               "animals.txt",
    "cat":                "animals.txt",
    "dog":                "animals.txt",
    "fish":               "animals.txt",

    # ── animals_dinosaur.txt (new) ───────────────────────────────────────────
    "dinosaur":           "animals_dinosaur.txt",

    # ── animals_fantasy.txt (new) ────────────────────────────────────────────
    "fantasy-creature":   "animals_fantasy.txt",
    "monster":            "animals_fantasy.txt",

    # ── sfw_characters.txt (existing) ────────────────────────────────────────
    "alien":              "sfw_characters.txt",
    "angel":              "sfw_characters.txt",
    "class":              "sfw_characters.txt",
    "deity":              "sfw_characters.txt",
    "name-female":        "sfw_characters.txt",
    "name-male":          "sfw_characters.txt",
    "noun-fantasy":       "sfw_characters.txt",
    "superhero":          "sfw_characters.txt",
    "tribe":              "sfw_characters.txt",

    # ── sfw_characters_scenario.txt (new) ────────────────────────────────────
    "scenario":           "sfw_characters_scenario.txt",             # multi-sentence; too long for concept files
    "scenario-fantasy":   "sfw_characters_scenario.txt",
    "scenario-scifi":     "sfw_characters_scenario.txt",
    "scenario2":          "sfw_characters_scenario.txt",

    # ── sfw_characters_subject.txt (new) ─────────────────────────────────────
    "subject":            "sfw_characters_subject.txt",             # phrase-level ("a woman at a cafe")
    "subject-fantasy":    "sfw_characters_subject.txt",
    "subject-scifi":      "sfw_characters_subject.txt",

    # ── humans.txt (existing) ────────────────────────────────────────────────
    "occupation":         "humans.txt",

    # ── locations.txt (existing) ─────────────────────────────────────────────
    "interior":           "locations.txt",
    "location":           "locations.txt",
    "noun-landscape":     "locations.txt",

    # ── locations_specific.txt (existing) ────────────────────────────────────
    "civilization":       "locations_specific.txt",
    "national-park":      "locations_specific.txt",
    "pop-location":       "locations_specific.txt",
    "site":               "locations_specific.txt",
    "fantasy-setting":    "locations.txt",

    # ── colors.txt (existing) ────────────────────────────────────────────────
    "background-color":   "colors.txt",
    "color":              "colors.txt",

    # ── sfw_descriptions.txt (existing) ──────────────────────────────────────
    "adj-general":        "sfw_descriptions.txt",
    "blonde":             "sfw_descriptions.txt",    # granular hair detail
    "skin-color":         "sfw_descriptions.txt",

    # ── sfw_descriptions_nationality.txt (existing) ──────────────────────────
    "nationality":        "sfw_descriptions_nationality.txt",
    "race":               "sfw_descriptions_nationality.txt",

    # ── sfw_descriptions_eye_color.txt (existing) ────────────────────────────
    "eye-color":          "sfw_descriptions_eyes.txt",

    # ── artists.txt (existing) ───────────────────────────────────────────────
    "artist":             "artists.txt",
    "artist-black-white": "artists.txt",
    "artist-c":           "artists.txt",
    "artist-cartoon":     "artists.txt",
    "artist-concept":     "artists.txt",
    "artist-csv":         "artists.txt",    # large; many duplicates with artist.txt
    "artist-dig1":        "artists.txt",
    "artist-dig2":        "artists.txt",
    "artist-dig3":        "artists.txt",
    "artist-director":    "artists.txt",
    "artist-fantasy":     "artists.txt",
    "artist-fareast":     "artists.txt",
    "artist-horror":      "artists.txt",
    "artist-n":           "artists.txt",
    "artist-photographer":"artists.txt",
    "artist-scifi":       "artists.txt",
    "artist-scribbles":   "artists.txt",
    "artist-special":     "artists.txt",
    "artist-surreal":     "artists.txt",
    "artist-weird":       "artists.txt",
    "artist-botanical":   "painters.txt",
    "artist-fineart":     "painters.txt",
    "artist-anime":       "mangakas.txt",
    "artist-ukioe":       "mangakas.txt",

    # ── positions / angles ──────────────────────────────────────────────────
    "angle":              "angles_and_views.txt",
    "pose":               "positions.txt",

    # ── times.txt (existing) ────────────────────────────────────────────────
    "decade":             "times.txt",
    "time":               "times.txt",

    # ── sfw_dress.txt (existing) ────────────────────────────────────────────
    "belt":               "sfw_dress.txt",
    "clothing":           "sfw_dress.txt",
    "clothing-male":      "sfw_dress.txt",
    "earrings":           "sfw_dress.txt",
    "headwear-female":    "sfw_dress.txt",
    "headwear-male":      "sfw_dress.txt",
    "neckwear":           "sfw_dress.txt",
    "purse":              "sfw_dress.txt",
    "suit-female":        "sfw_dress.txt",
    "suit-male":          "sfw_dress.txt",
    "costume-female":     "sfw_dress.txt",
    "costume-male":       "sfw_dress.txt",

    # ── sfw_expressions.txt (existing) ──────────────────────────────────────
    "expression":         "sfw_expressions.txt",

    # ── emoji.txt (new) ─────────────────────────────────────────────────────
    "emoji":              "emoji.txt",
    "emoji-combo":        "emoji_combos.txt",


    # ── Needs manual review (phrase-level / mixed content) ──────────────────
    "pop-culture":        None,             # film/TV/game franchise titles; no clean existing target
    "setting":            None,
    "underwater":         None,

    "trippy":             None,             # psychedelic / trippy modifiers
    "quantity":           None,

    # ── Explicit skip ───────────────────────────────────────────────────────
    "actor":              "skip",    # celebrity names
    "actress":            "skip",    # celebrity names
    "bangs":              "skip",    # granular hair detail
    "body-fit":           "skip",
    "body-framing":       "skip",
    "body-light":         "skip",
    "body-shape":         "skip",
    "body-shape2":        "skip",
    "body-short":         "skip",
    "body-tall":          "skip",
    "braid":              "skip",    # granular hair detail
    "celeb":              "skip",    # celebrity names
    "female-adult":       "skip",
    "female-young":       "skip",
    "hair-accessory":     "skip",
    "hair-color":         "skip",
    "hair-female":        "skip",
    "hair-female-short":  "skip",
    "hair-length":        "skip",
    "hair-male":          "skip",
    "identity":           "skip",
    "makeup":             "skip",
    "male-adult":         "skip",
    "male-young":         "skip",
    "neg-weight":         "skip",    # prompt weight syntax tokens
    "noun-beauty":        "skip",
    "noun-horror":        "skip",    # likely mostly blacklisted
    "noun-romance":       "skip",
    "punk":               "skip",     # punk sub-genre aesthetics
}

ARTIST_TARGETS: frozenset[str] = frozenset({"artists.txt", "painters.txt", "mangakas.txt"})

# ---------------------------------------------------------------------------
# Script-level blacklist override patterns
#
# Any concept matching one of these patterns is treated as importable even if
# the blacklist checker flags it (false positives from substring matching).
# Patterns are matched case-insensitively against the full concept string.
# ---------------------------------------------------------------------------
BLACKLIST_OVERRIDE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"colon[iy]", re.IGNORECASE),  # colony, colonial, colonize, etc.
)

# ---------------------------------------------------------------------------
# Script-level supplementary blacklist patterns
#
# Concepts matching any of these are treated as blacklisted even if the
# blacklist checker does not flag them (false negatives from the base list).
# Patterns are matched case-insensitively against the full concept string.
# ---------------------------------------------------------------------------
SCRIPT_BLACKLIST_PATTERNS: tuple[re.Pattern, ...] = (
    # clothing — revealing / anatomical items not caught by base blacklist
    re.compile(r"pelvic",          re.IGNORECASE),  # pelvic curtain
    re.compile(r"\btanga\b",       re.IGNORECASE),  # thong-equivalent garment
    re.compile(r"\bslingshot\b",   re.IGNORECASE),  # slingshot swimsuit
    re.compile(r"see.through",     re.IGNORECASE),  # see-through
    re.compile(r"school swimsuit", re.IGNORECASE),  # anime-context problematic

    # dark / occult class archetypes missed by base blacklist
    re.compile(r"\bdemon",         re.IGNORECASE),  # demon beast, demonbinder, demonologist, etc.
    re.compile(r"\bdevil\b",       re.IGNORECASE),  # priest of the devil
    re.compile(r"\bhell",          re.IGNORECASE),  # hellion, hellfire, etc.
    re.compile(r"\bdeath\b",       re.IGNORECASE),  # death dealer, death knight
    re.compile(r"\bdeadwalker\b",  re.IGNORECASE),  # deadwalker
    re.compile(r"\bthrall\b",      re.IGNORECASE),  # void thrall
    re.compile(r"diabol",          re.IGNORECASE),  # diabolist
    re.compile(r"\bpyromaniac\b",  re.IGNORECASE),  # pyromaniac

    # body — noun-general items not caught by base blacklist
    re.compile(r"\bbreast\b",      re.IGNORECASE),  # breast
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_line_like_concepts_load(line: str) -> str:
    """Mirror sd_runner.concepts.Concepts.load line handling."""
    val = ""
    for c in line:
        if c == "#":
            break
        val += c
    return val.strip()


def load_concepts_from_path(filepath: Path) -> list[str]:
    out: list[str] = []
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                v = _parse_line_like_concepts_load(line)
                if v:
                    out.append(v)
    except OSError as e:
        print(f"Warning: could not read {filepath}: {e}", file=sys.stderr)
    return out


def is_nsfw_wildcard_file(name: str) -> bool:
    n = name.lower()
    return (
        "nsfw" in n or
        "gender" in n or
        "supermodel" in n or
        "sex" in n or
        "swimwear" in n or
        "public" in n or
        "photoshoot" in n or
        "romance" in n or
        "horror" in n or
        "beauty" in n or
        "porn" in n or
        "erotic" in n or
        "nude" in n or
        "nudity" in n or
        "naked" in n or
        "lipstick" in n or
        "legwear" in n or
        "heels" in n or
        "eyeliner" in n or
        "dress" in n or
        "clothing-female" in n or
        "choker" in n or
        "body-heavy" in n or
        "body-poor" in n
    )


def _try_load_blacklist() -> bool:
    """Attempt to load the blacklist via BlacklistWindow.set_blacklist(). Returns True if loaded."""
    try:
        from ui_qt.prompts.blacklist_window import BlacklistWindow
        from sd_runner.blacklist import Blacklist
        BlacklistWindow.set_blacklist()
        return not Blacklist.is_empty()
    except Exception:
        return False


def _make_blacklist_checker(blacklist_loaded: bool):
    """Return a function concept -> bool that returns True if blacklisted."""
    if not blacklist_loaded:
        return lambda _: False
    try:
        from sd_runner.blacklist import Blacklist
        def check(concept: str) -> bool:
            return Blacklist.get_violation_item(concept) is not None
        return check
    except Exception:
        return lambda _: False


def build_repo_concept_set(
    *,
    include_dictionary: bool,
    include_nsfw: bool,
    include_nsfl: bool,
    case_sensitive: bool,
) -> set[str]:
    from sd_runner.concepts import Concepts
    category_states = {
        "SFW": True,
        "NSFW": bool(include_nsfw),
        "NSFL": bool(include_nsfl),
        "Art Styles": True,
        "Dictionary": bool(include_dictionary),
    }
    cmap = Concepts.get_concepts_map(category_states)
    exact: set[str] = set()
    for _fn, concepts in cmap.items():
        exact.update(concepts)
    if case_sensitive:
        return exact
    return {c.casefold() for c in exact}


def _concepts_dir() -> Path:
    return Path(PROJECT_ROOT) / "concepts"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare wildcards .txt lines to repo concept union, with target-file mapping and blacklist filtering."
    )
    parser.add_argument(
        "--wildcards-dir",
        type=Path,
        default=Path("concepts") / "temp" / "sd-wildcards" / "wildcards",
    )
    parser.add_argument("--include-dictionary", action="store_true")
    parser.add_argument("--include-nsfw-categories", action="store_true")
    parser.add_argument("--include-nsfw-wildcard-files", action="store_true")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument(
        "--max-missing-list", type=int, default=40,
        help="Max missing lines to print per file (default: 40; 0 = suppress).",
    )
    parser.add_argument(
        "--csv", type=Path, default=Path(PROJECT_ROOT) / "wildcard_coverage.csv",
        help="Path to write CSV summary (default: <project-root>/wildcard_coverage.csv).",
    )
    parser.add_argument(
        "--export-dir", action="store_true", default=False,
        help="Write per-target importable-concept files into the project's concepts/ directory. "
             "Each file is named after its target and contains lines not yet "
             "in the repo that also pass the blacklist check.",
    )
    parser.add_argument(
        "--skip-blacklist", action="store_true",
        help="Disable blacklist filtering of missing lines.",
    )
    parser.add_argument(
        "--show-unmapped", action="store_true",
        help="Show full detail for files with no mapping (default: brief summary only).",
    )
    args = parser.parse_args()

    wild_dir: Path = args.wildcards_dir
    if not wild_dir.is_dir():
        print(f"Error: wildcards directory not found: {wild_dir.resolve()}", file=sys.stderr)
        return 1

    # --- Blacklist setup ---------------------------------------------------
    blacklist_loaded = False
    if not args.skip_blacklist:
        blacklist_loaded = _try_load_blacklist()
        if blacklist_loaded:
            from sd_runner.blacklist import Blacklist
            print(f"Blacklist loaded: {len(Blacklist.TAG_BLACKLIST)} items")
        else:
            print("Blacklist not loaded (run with --skip-blacklist to suppress this warning).")
    is_blacklisted = _make_blacklist_checker(blacklist_loaded)

    # --- Repo concept set --------------------------------------------------
    repo_set = build_repo_concept_set(
        include_dictionary=args.include_dictionary,
        include_nsfw=args.include_nsfw_categories,
        include_nsfl=args.include_nsfw_categories,
        case_sensitive=args.case_sensitive,
    )

    def norm(s: str) -> str:
        return s if args.case_sensitive else s.casefold()

    concepts_dir = _concepts_dir()

    txt_files = sorted(wild_dir.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files under {wild_dir}", file=sys.stderr)
        return 1

    print(f"\nRepo concept union size : {len(repo_set)}")
    print(f"Wildcards dir           : {wild_dir.resolve()}")
    print()

    # --- Accumulate results ------------------------------------------------
    csv_rows: list[tuple] = []
    export_buckets: dict[str, list[str]] = defaultdict(list)
    target_importable: dict[str, int] = defaultdict(int)

    skipped_nsfw: list[str] = []
    skipped_explicit: list[str] = []
    unmapped: list[str] = []
    # Collect mapped/needs-review results for sorted printing
    mapped_results: list[dict] = []

    for fp in txt_files:
        stem = fp.stem

        # Pre-filter: NSFW filenames
        if not args.include_nsfw_wildcard_files and is_nsfw_wildcard_file(fp.name):
            skipped_nsfw.append(fp.name)
            continue

        # Resolve mapping
        if stem not in WILDCARD_TO_TARGET:
            lines = load_concepts_from_path(fp)
            present = sum(1 for ln in lines if norm(ln) in repo_set)
            n = len(lines)
            pct = 100.0 * present / n if n else 0.0
            unmapped.append(fp.name)
            csv_rows.append((fp.name, "", "unmapped", n, present, n - present, 0, n - present, pct))
            continue

        target = WILDCARD_TO_TARGET[stem]

        if target == "skip":
            skipped_explicit.append(fp.name)
            continue

        # Mapped (target is a str or None for needs-review)
        lines = load_concepts_from_path(fp)
        n = len(lines)
        present = 0
        missing_raw: list[str] = []
        for ln in lines:
            if norm(ln) in repo_set:
                present += 1
            else:
                missing_raw.append(ln)

        miss_n = len(missing_raw)
        pct = 100.0 * present / n if n else 0.0

        blacklisted_lines: list[str] = []
        importable: list[str] = []
        for ln in missing_raw:
            base_hit = is_blacklisted(ln) and not any(p.search(ln) for p in BLACKLIST_OVERRIDE_PATTERNS)
            script_hit = any(p.search(ln) for p in SCRIPT_BLACKLIST_PATTERNS)
            if base_hit or script_hit:
                blacklisted_lines.append(ln)
            else:
                importable.append(ln)

        bl_count = len(blacklisted_lines)
        imp_count = len(importable)
        is_new_file = target is not None and not (concepts_dir / target).exists()
        target_label = target if target is not None else "— needs review —"

        mapped_results.append(dict(
            filename=fp.name,
            target=target,
            target_label=target_label,
            is_new_file=is_new_file,
            n=n, present=present, miss_n=miss_n,
            bl_count=bl_count, imp_count=imp_count, pct=pct,
            importable=importable,
            blacklisted_lines=blacklisted_lines,
        ))

        csv_rows.append((
            fp.name, target_label, "new" if is_new_file else "existing",
            n, present, miss_n, bl_count, imp_count, pct
        ))

        if target is not None and importable:
            export_buckets[target].extend(importable)
            target_importable[target] += imp_count

    # --- Print results: mapped files grouped by target, needs-review last ---
    # Sort: mapped (target str) by target name then filename; needs-review (target None) at end
    mapped_results.sort(key=lambda r: (r["target"] is None, r["target_label"], r["filename"]))

    for r in mapped_results:
        new_tag = "  (NEW FILE)" if r["is_new_file"] else ""
        print(f"=== {r['filename']}  →  {r['target_label']}{new_tag}")
        print(f"  lines: {r['n']}  present: {r['present']}  missing: {r['miss_n']}  ({r['pct']:.1f}% covered)")
        if blacklist_loaded:
            print(f"  blacklisted: {r['bl_count']}  importable: {r['imp_count']}")
            for m in r["blacklisted_lines"]:
                print(f"  [blacklisted] {m}")
        if r["target"] is None:
            for m in r["importable"]:
                print(f"    - {m}")
        print()

    # --- Compact summaries of skipped / unmapped ---------------------------
    if skipped_nsfw:
        print(f"Skipped (NSFW filename filter): {len(skipped_nsfw)} files")
        for name in skipped_nsfw:
            print(f"  {name}")
        print()

    if skipped_explicit:
        print(f"Skipped (explicit 'skip' mapping): {len(skipped_explicit)} files")
        for name in skipped_explicit:
            print(f"  {name}")
        print()

    if unmapped:
        label = "Full detail above" if args.show_unmapped else "use --show-unmapped for detail"
        print(f"Unmapped files ({label}): {len(unmapped)}")
        for name in unmapped:
            print(f"  {name}")
        print()

    # --- Target summary ----------------------------------------------------
    if target_importable:
        print("=== Importable lines by target file ===")
        for tgt, count in sorted(target_importable.items(), key=lambda x: -x[1]):
            is_new = not (concepts_dir / tgt).exists()
            tag = "  (NEW)" if is_new else ""
            print(f"  {count:>5}  {tgt}{tag}")
        print()

    # --- Blacklisted artists summary ---------------------------------------
    blacklisted_artists: set[str] = set()
    for r in mapped_results:
        if r["target"] in ARTIST_TARGETS:
            blacklisted_artists.update(r["blacklisted_lines"])
    if blacklisted_artists:
        print(f"=== Blacklisted artists (requires case-by-case review): {len(blacklisted_artists)} ===")
        for name in sorted(blacklisted_artists, key=str.casefold):
            print(f"  {name}")
        print()

    # --- CSV output --------------------------------------------------------
    if args.csv:
        import csv
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "file", "target_file", "file_status",
                "lines", "present", "missing",
                "blacklisted", "importable", "coverage_pct",
            ])
            for row in csv_rows:
                name, tgt, status, n, pres, miss, bl, imp, pct = row
                w.writerow([name, tgt, status, n, pres, miss, bl, imp, f"{pct:.2f}"])
        print(f"Wrote CSV: {args.csv.resolve()}")

    # --- Export ------------------------------------------------------------
    if args.export_dir:
        export_dir = Path(PROJECT_ROOT) / "concepts"
        export_dir.mkdir(parents=True, exist_ok=True)
        total_appended = 0
        for target_file, lines in sorted(export_buckets.items()):
            out_path = export_dir / target_file
            is_new = not out_path.exists()

            # Seed seen-set with lines already in the target file so we never duplicate
            existing = load_concepts_from_path(out_path) if not is_new else []
            seen: set[str] = {norm(ln) for ln in existing}

            deduped: list[str] = []
            for ln in lines:
                key = norm(ln)
                if key not in seen:
                    seen.add(key)
                    deduped.append(ln)

            with open(out_path, "a", encoding="utf-8") as f:
                f.write("\n\n# --- sd-wildcards merge ---\n")
                for ln in deduped:
                    f.write(ln + "\n")
            total_appended += len(deduped)
        print(f"Export complete: {total_appended} lines appended across {len(export_buckets)} files.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
