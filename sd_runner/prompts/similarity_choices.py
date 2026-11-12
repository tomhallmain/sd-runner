"""``[[~a,b,c]]`` choice sets: resolved to the option most similar to a reference image.

The reference image is known only per generation, after the prompt has been
generated, so ``generate_prompt`` replaces each set with a placeholder
(``⟦~0⟧``) and keeps its options in a list of ``SimilarityChoice``.
``resolve_prompts`` substitutes the placeholders once the image is known.
The placeholder holds no comma, letter or bracket, so the stages between --
blacklist and exclusion filtering, sparse mixing, random stops and returns --
treat it as an ordinary word and cannot split it.

Weights (``woman:2``) are accepted and dropped. A similarity set nested inside
another choice set is not supported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
import re
from typing import Callable, Optional

from lib.logging_setup import get_logger
from lib.translations import _

logger = get_logger("prompts.similarity_choices")

SET_MARKER = "~"
SET_OPEN = "[[" + SET_MARKER
PLACEHOLDER = "⟦~{0}⟧"
PLACEHOLDER_PATTERN = re.compile("⟦~(\\d+)⟧")


@dataclass
class SimilarityChoice:
    source: str
    """The set as written, ``[[~...]]`` included."""
    options: list[str] = field(default_factory=list)


def contains_similarity_set(text: str) -> bool:
    return bool(text) and SET_OPEN in text


def contains_placeholder(text: str) -> bool:
    return bool(text) and PLACEHOLDER_PATTERN.search(text) is not None


def iter_choice_sets(text: str):
    """Yield ``(start, end, inner)`` for each top-level ``[[...]]`` in *text*."""
    # Deferred: prompter imports this module.
    from sd_runner.prompts.prompter import Prompter

    i = 0
    while i < len(text) - 1:
        if text[i:i + 2] == "[[":
            inner_close = Prompter._find_matching_bracket(text, i + 1, "[", "]")
            if inner_close != -1 and inner_close + 1 < len(text) and text[inner_close + 1] == "]":
                yield i, inner_close + 2, text[i + 2:inner_close]
                i = inner_close + 2
                continue
        i += 1


def similarity_set_options(content: str) -> list[str]:
    """The options of a set's content after the marker, flattened and deduplicated.

    Nested ``[a,b]`` groups are expanded, so ``"[red,blue] car,bike"`` gives
    ``["red car", "blue car", "bike"]``. Weights are dropped.
    """
    from sd_runner.prompts.prompter import Prompter

    options = Prompter._split_choice_options(content) or ([content] if content.strip() else [])
    flat: list[str] = []
    for option in options:
        option_text, _weight = Prompter._split_option_weight(option)
        for expanded, _nested_weight in Prompter._expand_nested_choices(option_text):
            expanded = expanded.strip()
            if expanded:
                flat.append(expanded)
    return list(dict.fromkeys(flat))


def extract_similarity_sets(text: str, choices: list[SimilarityChoice]) -> str:
    """Replace each top-level ``[[~...]]`` in *text* with a placeholder.

    The options are appended to *choices*; the placeholder carries the index.
    A set already in *choices*, written the same way, reuses its index, so
    text compared with an earlier extraction (a prompt that already holds the
    positive tags) still matches. A set with no options is removed. A range (``[[~1--5]]``) has nothing to
    compare against an image, so it loses its marker and stays a normal
    choice set.
    """
    if not contains_similarity_set(text):
        return text
    from sd_runner.prompts.prompter import Prompter

    out: list[str] = []
    cursor = 0
    for start, end, inner in iter_choice_sets(text):
        if not inner.startswith(SET_MARKER):
            continue
        content = inner[len(SET_MARKER):]
        out.append(text[cursor:start])
        cursor = end
        if Prompter._expand_range(content):
            logger.warning(_(
                "A range cannot be chosen by image similarity, so it is resolved at random: {0}"
            ).format(text[start:end]))
            out.append("[[" + content + "]]")
            continue
        source = text[start:end]
        existing = next((n for n, c in enumerate(choices) if c.source == source), None)
        if existing is not None:
            out.append(PLACEHOLDER.format(existing))
            continue
        options = similarity_set_options(content)
        if options:
            choices.append(SimilarityChoice(source, options))
            out.append(PLACEHOLDER.format(len(choices) - 1))
    out.append(text[cursor:])
    return "".join(out)


def restore_similarity_sets(text: str, choices: list[SimilarityChoice]) -> str:
    """Put the sets as written back in place of their placeholders."""
    if not contains_placeholder(text):
        return text

    def _source(match: re.Match) -> str:
        index = int(match.group(1))
        return choices[index].source if 0 <= index < len(choices) else ""

    return PLACEHOLDER_PATTERN.sub(_source, text)


def reference_image_path(ip_adapter=None, control_net=None, prompt_image_path: str = "") -> Optional[str]:
    """The image to compare options against: the IP adapter's, else the
    ControlNet's, else the run's prompt image."""
    for adapter in (ip_adapter, control_net):
        path = getattr(adapter, "id", None) if adapter is not None else None
        if path:
            return path
    return prompt_image_path or None


def choose_option(
    choice: SimilarityChoice,
    image_path: Optional[str],
    on_fallback: Callable[[str], None],
) -> str:
    """The option closest to *image_path*, or a random one if that cannot be scored."""
    if not choice.options:
        return ""
    if image_path:
        from sd_runner.prompts.reference_similarity import ReferenceSimilarityEngine
        engine = ReferenceSimilarityEngine.get()
        if engine is not None:
            match = engine.best_match(image_path, choice.options)
            if match is not None:
                index, scores = match
                from sd_runner.config import config
                if config.debug:
                    ranked = ", ".join(f"{o}={s:.4f}" for o, s in zip(choice.options, scores))
                    logger.debug(f"Similarity choice {choice.source} against {image_path}: "
                                 f"{choice.options[index]} ({ranked})")
                return choice.options[index]
            on_fallback(_("the reference image could not be scored"))
        else:
            on_fallback(_("no similarity model is available"))
    else:
        on_fallback(_("there is no reference image"))
    return random.choice(choice.options)


def resolve_prompts(
    positive: str,
    negative: str,
    choices: list[SimilarityChoice],
    image_path: Optional[str],
    on_fallback: Callable[[str], None],
) -> tuple[str, str]:
    """Substitute every placeholder in *positive* and *negative*.

    A placeholder that occurs more than once gets the same option each time.
    """
    picks: dict[int, str] = {}

    def _pick(match: re.Match) -> str:
        index = int(match.group(1))
        if index not in picks:
            picks[index] = (
                choose_option(choices[index], image_path, on_fallback)
                if 0 <= index < len(choices) else ""
            )
        return picks[index]

    if contains_placeholder(positive):
        positive = PLACEHOLDER_PATTERN.sub(_pick, positive)
    if contains_placeholder(negative):
        negative = PLACEHOLDER_PATTERN.sub(_pick, negative)
    return positive, negative
