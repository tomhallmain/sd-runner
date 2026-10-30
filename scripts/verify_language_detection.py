"""Checks what the blacklist's language detection assumes about Lingua.

Needs only lingua-language-detector and the concept folders, so it can run
before any of the application does. Prints a report and writes it as JSON.

    python scripts/verify_language_detection.py
    python scripts/verify_language_detection.py --classifier reddesert/urban_dictionary_corpus_nsfw_detection

The sweep places each synthetic prompt the way detect_basket does, without
importing it, and reports how often a language present was missed. Its German
and English data is the repo's own. The other languages have only the short
phrases below, so their numbers are thin evidence.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import itertools
import json
import os
import platform
import random
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISTRIBUTION = "lingua-language-detector"
LATIN_CODES = ("de", "es", "fr", "it", "pt")
HAN_CODES = ("zh", "ja")
EXPECTED_PYTHON = (3, 11)
MIN_LETTERS_GRID = (6, 8, 10, 12, 16, 20)
MIN_CONFIDENCE_GRID = (0.05, 0.1, 0.15, 0.2, 0.3)
CONFIDENT_GRID = (0.4, 0.5, 0.6, 0.7, 0.8)

PHRASES = {
    "es": ["una casa antigua", "el gato duerme", "montañas nevadas al amanecer", "mujer con vestido rojo",
           "un bosque oscuro", "calle mojada de noche", "flores en el jardín", "barco de vela en el mar"],
    "fr": ["une vieille maison", "le chat dort", "montagnes enneigées au lever du jour", "femme en robe rouge",
           "une forêt sombre", "rue mouillée la nuit", "fleurs dans le jardin", "voilier sur la mer"],
    "it": ["una vecchia casa", "il gatto dorme", "montagne innevate all'alba", "donna con vestito rosso",
           "una foresta oscura", "strada bagnata di notte", "fiori nel giardino", "barca a vela sul mare"],
    "pt": ["uma casa antiga", "o gato dorme", "montanhas nevadas ao amanhecer", "mulher de vestido vermelho",
           "uma floresta escura", "rua molhada à noite", "flores no jardim", "barco à vela no mar"],
    "zh": ["一座古老的房子", "猫在睡觉", "清晨的雪山", "穿红裙子的女人", "黑暗的森林", "夜晚潮湿的街道", "花园里的花", "海上的帆船"],
    "ja": ["古い家", "眠っている猫", "夜明けの雪山", "赤いドレスの女性", "暗い森", "夜の濡れた通り", "庭の花", "海の帆船"],
}
THREAD_SAMPLE = ["Die Katze schläft", "a cat sleeping", "una casa antigua", "le chat dort", "猫在睡觉"]


def section(title):
    print(f"\n== {title} ==")


def concept_lines(folder):
    lines = {}
    path = os.path.join(REPO_ROOT, folder)
    for name in sorted(os.listdir(path)):
        if not name.endswith(".txt") or name == "dictionary.txt":
            continue
        with open(os.path.join(path, name), encoding="utf-8", errors="replace") as f:
            content = [line.split("#", 1)[0].strip() for line in f]
        lines[name] = [line for line in content if line]
    return lines


def tag_corpus():
    """German and English tags: translated lines that differ, and their sources."""
    english = concept_lines("concepts")
    german = concept_lines("Konzepte")
    pairs = []
    for name, translated in german.items():
        source = english.get(name, [])
        if len(source) == len(translated):
            pairs += [(e, g) for e, g in zip(source, translated) if e != g and len(e) <= 60 and len(g) <= 60]
    return [e for e, _g in pairs], [g for _e, g in pairs]


def build(codes):
    from lingua import IsoCode639_1, LanguageDetectorBuilder

    iso_codes = [getattr(IsoCode639_1, code.upper()) for code in sorted(set(codes) | {"en"})]
    detector = LanguageDetectorBuilder.from_iso_codes_639_1(*iso_codes).build()

    def score(text):
        return tuple((value.language.iso_code_639_1.name.lower(), value.value)
                     for value in detector.compute_language_confidence_values(text))

    return score


def check_environment(report):
    section("Version and Python")
    version = importlib.metadata.version(DISTRIBUTION)
    python = platform.python_version()
    matches = sys.version_info[:2] == EXPECTED_PYTHON
    print(f"{DISTRIBUTION} {version}, Python {python}")
    if not matches:
        print(f"WARNING: the project and its build use Python {EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}")
    report["environment"] = {"lingua": version, "python": python, "python_matches_project": matches}


def check_api(report):
    section("API")
    from lingua import IsoCode639_1

    missing = [code for code in LATIN_CODES + HAN_CODES if not hasattr(IsoCode639_1, code.upper())]
    scores = build(("de",))("Die Katze schläft auf dem warmen Sofa")
    total = sum(value for _code, value in scores)
    ordered = all(a[1] >= b[1] for a, b in zip(scores, scores[1:]))
    german_won = bool(scores) and scores[0][0] == "de"
    names = {name: hasattr(IsoCode639_1, name) for name in ("TL", "FIL", "TLH", "KAB")}
    print(f"language scores for a German sentence: {scores}")
    print(f"sum {total:.3f}, highest first: {ordered}, German on top: {german_won}")
    print(f"in-scope codes missing: {missing or 'none'}; other codes known: {names}")
    report["api"] = {"missing_codes": missing, "sum": total, "ordered": ordered,
                     "german_on_top": german_won, "other_codes": names}


def check_packaging(report):
    section("Packaging")
    files = importlib.metadata.files(DISTRIBUTION) or []
    entries = []
    for file in files:
        path = str(file.locate())
        entries.append((str(file), os.path.getsize(path) if os.path.isfile(path) else 0))
    entries.sort(key=lambda entry: entry[1], reverse=True)
    for name, size in entries[:10]:
        print(f"{size / 1048576:10.1f} MB  {name}")
    licences = [name for name, _size in entries
                if any(word in name.lower() for word in ("licen", "notice"))]
    data_files = [name for name, size in entries
                  if size > 1048576 and not name.endswith((".pyd", ".so", ".dylib"))]
    print(f"licence and notice files: {licences or 'none'}")
    print(f"large files outside the extension: {data_files or 'none, so the models are compiled in'}")
    report["packaging"] = {"total_mb": sum(size for _name, size in entries) / 1048576,
                           "licence_files": licences, "large_data_files": data_files}


def resident_memory_mb():
    try:
        import psutil
    except ImportError:
        return None
    return psutil.Process().memory_info().rss / 1048576


def check_memory(report):
    section("Memory per language (lazy loading)")
    steps = []
    codes = []
    for code in LATIN_CODES + HAN_CODES:
        codes.append(code)
        build(codes)("Die Katze schläft auf dem warmen Sofa, une vieille maison")
        memory = resident_memory_mb()
        if memory is None:
            print("psutil is not installed; skipped")
            report["memory"] = None
            return
        steps.append({"languages": list(codes), "resident_mb": memory})
        print(f"{len(codes)} languages: {memory:.0f} MB")
    report["memory"] = steps


def check_threads(report):
    section("Thread safety")
    score = build(LATIN_CODES + HAN_CODES)
    expected = {text: score(text) for text in THREAD_SAMPLE}
    texts = THREAD_SAMPLE * 400
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(score, texts))
    mismatches = sum(result != expected[text] for text, result in zip(texts, results))
    print(f"{len(texts)} calls on 8 threads, {mismatches} differed from single-thread results")
    report["threads"] = {"calls": len(texts), "mismatches": mismatches}


def check_speed(report, tags):
    section("Speed")
    score = build(LATIN_CODES + HAN_CODES)
    score("warm up the models")
    sample = tags[:200]
    start = time.perf_counter()
    for tag in sample:
        score(tag)
    per_tag = (time.perf_counter() - start) / len(sample) * 1000
    pooled = ", ".join(sample[:12])
    start = time.perf_counter()
    score(pooled)
    pooled_ms = (time.perf_counter() - start) * 1000
    print(f"{per_tag:.2f} ms per tag, {pooled_ms:.2f} ms for 12 tags pooled")
    report["speed"] = {"ms_per_tag": per_tag, "ms_pooled_12_tags": pooled_ms}


def letters(text):
    return sum(char.isalpha() and ord(char) < 0x2E80 for char in text)


def is_han(text):
    return any(0x3400 <= ord(char) <= 0x9FFF or 0xF900 <= ord(char) <= 0xFAFF for char in text)


def has_kana(text):
    return any(0x3040 <= ord(char) <= 0x30FF for char in text)


def place(score, text, family, min_confidence, confident):
    """The placing step of detect_basket: returns (languages, widened)."""
    scores = [(code, value) for code, value in score(text) if code in family or code == "en"]
    if not scores or scores[0][1] < confident:
        return set(family), True
    found = {code for code, value in scores if value >= min_confidence}
    found.add(scores[0][0])
    return found & set(family), False


def basket(score, tags, min_letters, min_confidence, confident):
    alone, pooled, han = [], [], []
    languages = set()
    for tag in tags:
        if has_kana(tag):
            languages.add("ja")
        elif is_han(tag):
            han.append(tag)
        else:
            (alone if letters(tag) >= min_letters else pooled).append(tag)
    texts = [(tag, LATIN_CODES) for tag in alone]
    if pooled:
        texts.append((", ".join(pooled), LATIN_CODES))
    if han:
        texts.append((", ".join(han), HAN_CODES))
    widened = False
    for text, family in texts:
        found, text_widened = place(score, text, family, min_confidence, confident)
        languages |= found
        widened = widened or text_widened
    return languages, widened


def build_prompts(english, german, count, rng):
    """Comma-joined mixes: (tags, languages present). English adds no language."""
    prompts = []
    others = list(PHRASES)
    for _i in range(count):
        size = rng.randint(1, 8)
        kind = rng.choice(("english", "german", "english+german", "other", "english+other"))
        tags, present = [], set()
        for _n in range(size):
            if kind == "english" or (kind.startswith("english+") and rng.random() < 0.5):
                tags.append(rng.choice(english))
            elif kind in ("german", "english+german"):
                tags.append(rng.choice(german))
                present.add("de")
            else:
                code = rng.choice(others)
                tags.append(rng.choice(PHRASES[code]))
                present.add(code)
        prompts.append((tags, present))
    return prompts


def sweep(report, english, german, count):
    section("Thresholds")
    rng = random.Random(1)
    prompts = build_prompts(english, german, count, rng)
    detector = build(LATIN_CODES + HAN_CODES)
    cache = {}

    def score(text):
        if text not in cache:
            cache[text] = detector(text)
        return cache[text]

    results = []
    for min_letters, min_confidence, confident in itertools.product(
            MIN_LETTERS_GRID, MIN_CONFIDENCE_GRID, CONFIDENT_GRID):
        missed = extra = widened_count = 0
        for tags, present in prompts:
            found, widened = basket(score, tags, min_letters, min_confidence, confident)
            missed += bool(present - found)
            extra += bool(found - present)
            widened_count += widened
        results.append({
            "min_letters": min_letters, "min_confidence": min_confidence, "confident": confident,
            "missed": missed / count, "extra": extra / count, "widened": widened_count / count,
        })
    # Missing a language loses protection; an extra one only risks a collision.
    results.sort(key=lambda r: (r["missed"], r["widened"], r["extra"]))
    print(f"{count} prompts, {len(cache)} distinct detector inputs")
    print("min_letters min_conf confident   missed    extra  widened")
    for r in results[:12]:
        print(f"{r['min_letters']:>11} {r['min_confidence']:>8} {r['confident']:>9} "
              f"{r['missed']:>8.1%} {r['extra']:>8.1%} {r['widened']:>8.1%}")
    report["thresholds"] = {"prompts": count, "results": results}


def check_classifier(report, model_ref):
    section("Classifier")
    import transformers
    from transformers import AutoConfig

    model_config = AutoConfig.from_pretrained(model_ref)
    print(f"transformers {transformers.__version__}; model_type {model_config.model_type}; "
          f"saved with {getattr(model_config, 'transformers_version', 'unknown')}")
    report["classifier"] = {"transformers": transformers.__version__, "model_type": model_config.model_type,
                            "model_transformers_version": getattr(model_config, "transformers_version", None)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prompts", type=int, default=2000, help="Synthetic prompts in the threshold sweep")
    parser.add_argument("--output", default="language_detection_report.json", help="JSON report path")
    parser.add_argument("--classifier", default=None, help="Also check this classifier model id or path")
    args = parser.parse_args()

    try:
        import lingua  # noqa: F401
    except ImportError as e:
        print(f"lingua is not importable: {e}", file=sys.stderr)
        return 1

    report = {}
    english, german = tag_corpus()
    print(f"{len(english)} translated tag pairs from the repo")
    check_environment(report)
    check_api(report)
    check_packaging(report)
    check_memory(report)
    check_threads(report)
    check_speed(report, english + german)
    sweep(report, english, german, args.prompts)
    if args.classifier:
        check_classifier(report, args.classifier)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
