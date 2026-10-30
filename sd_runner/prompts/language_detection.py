"""Works out which non-English languages a prompt is likely to contain.

A prompt mixes languages from tag to tag, so the result is a basket: the union
over all tags, applied to every tag. Scripts other than Latin and Han are
placed by their Unicode block alone. Latin and Han text goes to the detector,
restricted to the languages that have blacklist items.

When a tag cannot be placed the basket grows, and a missing detector gives
every supported language, so a wrong guess can add collisions but never remove
protection. English has no language code and is never in a basket: items
without a language always apply.
"""

from dataclasses import dataclass
import functools
import threading
from typing import Callable, Iterable

from lib.logging_setup import get_logger
from sd_runner.config import config
from sd_runner.prompts.blacklist import Blacklist

logger = get_logger("prompts.language_detection")

# Set from the sweep in scripts/verify_language_detection.py. Those settings
# keep missed languages low and accept that English prompts often gain one, so
# the blacklist rows have to be chosen not to collide with English text.

#: A tag with at least this many Latin letters is detected on its own; shorter
#: ones give the detector too little, so they are pooled and detected together.
MIN_LETTERS = 10
#: A language at or above this confidence joins the basket.
MIN_CONFIDENCE = 0.3
#: Below this top confidence, every language the text could be in joins.
CONFIDENT = 0.4

_SCRIPT_RANGES = (
    ("greek", 0x0370, 0x03FF),
    ("cyrillic", 0x0400, 0x052F),
    ("hebrew", 0x0590, 0x05FF),
    ("arabic", 0x0600, 0x06FF),
    ("arabic", 0x0750, 0x077F),
    ("devanagari", 0x0900, 0x097F),
    ("thai", 0x0E00, 0x0E7F),
    ("hangul", 0x1100, 0x11FF),
    ("kana", 0x3040, 0x30FF),
    ("hangul", 0x3130, 0x318F),
    ("han", 0x3400, 0x4DBF),
    ("han", 0x4E00, 0x9FFF),
    ("hangul", 0xAC00, 0xD7AF),
    ("han", 0xF900, 0xFAFF),
)
_SCRIPT_LANGUAGES = {
    "greek": frozenset({"el"}),
    "cyrillic": frozenset({"ru", "uk", "bg"}),
    "hebrew": frozenset({"he"}),
    "arabic": frozenset({"ar", "fa", "ur"}),
    "devanagari": frozenset({"hi", "mr"}),
    "thai": frozenset({"th"}),
    "hangul": frozenset({"ko"}),
    "kana": frozenset({"ja"}),
}
#: Han alone does not separate these: 操 is a Chinese item, 操作 ordinary Japanese.
_HAN_LANGUAGES = frozenset({"zh", "ja"})
_NON_LATIN_LANGUAGES = _HAN_LANGUAGES.union(*_SCRIPT_LANGUAGES.values())

#: Replaces the Lingua binding: takes the language codes and returns the
#: scoring function. Lets the tests run without Lingua installed.
detector_hook: Callable[[frozenset[str]], Callable] | None = None

_lock = threading.Lock()
_detector = None
_detector_codes: frozenset[str] | None = None
_detector_unavailable = False
_supported_cache: tuple[str, frozenset[str]] | None = None


@dataclass(frozen=True)
class LanguageBasket:
    languages: frozenset[str] = frozenset()  # non-English codes; empty means English alone
    scores: tuple[tuple[str, float], ...] = ()  # best confidence per language, for logs and the preview
    widened: bool = False  # a tag could not be placed


def supported_languages() -> frozenset[str]:
    """The languages of the enabled tag items; only these are worth detecting."""
    global _supported_cache
    version = Blacklist.get_version()
    cached = _supported_cache
    if cached is not None and cached[0] == version:
        return cached[1]
    languages = frozenset(item.language for item in Blacklist.TAG_BLACKLIST
                          if item.enabled and item.language is not None)
    _supported_cache = (version, languages)
    return languages


def build_detector(codes: frozenset[str]) -> Callable[[str], tuple[tuple[str, float], ...]]:
    """A function scoring text over *codes* and English, highest confidence first."""
    if detector_hook is not None:
        return detector_hook(codes)
    from lingua import IsoCode639_1, LanguageDetectorBuilder

    iso_codes = [getattr(IsoCode639_1, code.upper()) for code in codes | {"en"}]
    detector = LanguageDetectorBuilder.from_iso_codes_639_1(*iso_codes).build()

    def score(text: str) -> tuple[tuple[str, float], ...]:
        return tuple((value.language.iso_code_639_1.name.lower(), value.value)
                     for value in detector.compute_language_confidence_values(text))

    return score


def _known_to_detector(codes: frozenset[str]) -> frozenset[str]:
    """The codes the detector has a model for. All of them if it cannot be asked."""
    if detector_hook is not None:
        return codes
    try:
        from lingua import IsoCode639_1
    except Exception:
        return codes
    return frozenset(code for code in codes if hasattr(IsoCode639_1, code.upper()))


def _get_detector(codes: frozenset[str]):
    """The shared detector for *codes*, rebuilt if they changed; None if there is none."""
    global _detector, _detector_codes, _detector_unavailable
    with _lock:
        if _detector_unavailable:
            return None
        if _detector is None or _detector_codes != codes:
            try:
                _detector = build_detector(codes)
            except Exception as e:
                _detector_unavailable = True
                logger.warning(f"Language detector unavailable, checking every language: {e}")
                return None
            _detector_codes = codes
            _scores.cache_clear()
        return _detector


@functools.lru_cache(maxsize=4096)
def _scores(text: str) -> tuple[tuple[str, float], ...]:
    # Every caller has just fetched the detector for the current codes, and a
    # rebuild clears this cache.
    return _detector(text)


def _script_of(char: str) -> str | None:
    code_point = ord(char)
    for script, low, high in _SCRIPT_RANGES:
        if low <= code_point <= high:
            return script
    return "latin" if char.isalpha() else None


@functools.lru_cache(maxsize=4096)
def _script_counts(tag: str) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for char in tag:
        script = _script_of(char)
        if script is not None:
            counts[script] = counts.get(script, 0) + 1
    return tuple(counts.items())


def _place(text: str, family: frozenset[str], best: dict[str, float]) -> tuple[frozenset[str], bool]:
    """The languages of *family* that *text* could be in, and whether it was widened."""
    scores = [(code, value) for code, value in _scores(text) if code in family or code == "en"]
    for code, value in scores:
        if code != "en":
            best[code] = max(best.get(code, 0.0), value)
    if not scores or scores[0][1] < CONFIDENT:
        return family, True
    found = {code for code, value in scores if value >= MIN_CONFIDENCE}
    found.add(scores[0][0])
    return frozenset(found) & family, False


def detect_basket(tags: Iterable[str]) -> LanguageBasket:
    """The languages likely present in *tags*, over the languages that have items."""
    supported = supported_languages()
    if not supported:
        return LanguageBasket()

    latin_languages = supported - _NON_LATIN_LANGUAGES
    han_languages = supported & _HAN_LANGUAGES
    languages: set[str] = set()
    alone: list[str] = []
    pooled: list[str] = []
    han_tags: list[str] = []
    has_latin = False

    for tag in tags:
        tag = tag.strip(" ()[]")
        counts = dict(_script_counts(tag))
        for script in counts:
            languages |= _SCRIPT_LANGUAGES.get(script, frozenset()) & supported
        if "han" in counts and "kana" not in counts:
            if len(han_languages) == 2:
                han_tags.append(tag)
            else:
                languages |= han_languages
        if "latin" in counts:
            has_latin = True
            (alone if counts["latin"] >= MIN_LETTERS else pooled).append(tag)

    detectable = _known_to_detector(latin_languages)
    if has_latin:
        # A language no model covers can never be detected, so it always applies.
        languages |= latin_languages - detectable

    texts = [(text, detectable) for text in alone] if detectable else []
    if pooled and detectable:
        texts.append((", ".join(pooled), detectable))
    if han_tags:
        texts.append((", ".join(han_tags), han_languages))

    best: dict[str, float] = {}
    widened = False
    if texts:
        if _get_detector(detectable | (han_languages if len(han_languages) == 2 else frozenset())) is None:
            return LanguageBasket(supported, (), True)
        for text, family in texts:
            found, text_widened = _place(text, family, best)
            languages |= found
            widened = widened or text_widened

    basket = LanguageBasket(
        frozenset(languages),
        tuple(sorted(best.items(), key=lambda entry: entry[1], reverse=True)),
        widened,
    )
    if config.debug:
        logger.debug(f"Language basket: {sorted(basket.languages)} scores={basket.scores} widened={basket.widened}")
    return basket


def reset_state() -> None:
    """Forget the detector and every cached result."""
    global _detector, _detector_codes, _detector_unavailable, _supported_cache
    with _lock:
        _detector = None
        _detector_codes = None
        _detector_unavailable = False
    _supported_cache = None
    _scores.cache_clear()
    _script_counts.cache_clear()
