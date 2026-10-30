"""Language codes as blacklist items and concept sets store them."""

import re

_PRIMARY_SUBTAG = re.compile(r"[a-z]{2,3}")


def _primary_subtag(code: str) -> str:
    return code.strip().replace("_", "-").split("-", 1)[0].lower()


def normalize_language_code(code: object) -> str | None:
    """The lowercase primary language subtag of *code*, or None.

    None, blank, English, and anything that is not a two- or three-letter
    primary subtag give None. English is the base language of the blacklist, so
    it has no code of its own.
    """
    if not isinstance(code, str):
        return None
    primary = _primary_subtag(code)
    if primary == "en" or not _PRIMARY_SUBTAG.fullmatch(primary):
        return None
    return primary


def is_invalid_language_code(code: object) -> bool:
    """Whether *code* normalised to None by being unusable, not by being English or blank."""
    if code is None:
        return False
    if not isinstance(code, str):
        return True
    return code.strip() != "" and normalize_language_code(code) is None and _primary_subtag(code) != "en"
