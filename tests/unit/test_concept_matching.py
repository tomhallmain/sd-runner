"""
Template-aware concept matching, and the blacklist check on adding concepts.

Concept lines outside dictionary.txt can be templates -- ``[[a,b]]`` choice sets
and ``$$name`` variables -- so matching compares what a line can expand to, not
its raw text. Adding a concept asks before writing one the blacklist would
filter at generation time.
"""

import pytest

from sd_runner.globals import BlacklistPromptMode
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.prompts.concepts import Concepts, NSFW

COLORS_FILE = "colors.txt"


@pytest.fixture
def concepts_dir(tmp_path, monkeypatch):
    (tmp_path / COLORS_FILE).write_text("amber\n[[red,blue]] car\n", encoding="utf-8")
    monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
    return tmp_path


def write_import(directory, *lines):
    path = directory / "to_import.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def read_concepts(path):
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# Concepts.template_texts
# ---------------------------------------------------------------------------

class TestTemplateTexts:
    def test_a_plain_line_yields_only_itself(self):
        assert Concepts.template_texts("blue car") == ("blue car",)

    def test_the_raw_line_comes_first(self):
        assert Concepts.template_texts("[[red,blue]] car")[0] == "[[red,blue]] car"

    def test_each_choice_is_expanded(self):
        texts = Concepts.template_texts("[[red,blue]] car")
        assert "red car" in texts and "blue car" in texts

    def test_nested_choices_are_expanded(self):
        texts = Concepts.template_texts("[[[red,blue] car,bike]]")
        assert {"red car", "blue car", "bike"} <= set(texts)

    def test_choice_weights_are_dropped(self):
        assert "red car" in Concepts.template_texts("[[red:3,blue]] car")

    def test_expansion_variables_are_dropped(self):
        assert "Far cry from" in Concepts.template_texts("Far cry from $$random_word")

    def test_an_oversized_template_falls_back_to_its_bare_words(self):
        template = " ".join("[[a,b,c]]" for _ in range(10))  # 3**10 expansions
        texts = Concepts.template_texts(template)
        assert len(texts) == 2
        assert "[" not in texts[1]


# ---------------------------------------------------------------------------
# Duplicate check on import
# ---------------------------------------------------------------------------

class TestCheckConceptExistsWithTemplates:
    def test_a_plain_concept_matches_a_template_that_expands_to_it(self):
        existing = {COLORS_FILE: {"[[red,blue]] car"}}
        matches = Concepts._check_concept_exists("blue car", existing, "other.txt")
        assert matches == [("[[red,blue]] car", COLORS_FILE)]

    def test_a_template_concept_matches_a_plain_line_it_expands_to(self):
        existing = {COLORS_FILE: {"blue car"}}
        matches = Concepts._check_concept_exists("[[green,blue]] car", existing, "other.txt")
        assert matches == [("blue car", COLORS_FILE)]

    def test_an_unrelated_template_does_not_match(self):
        existing = {COLORS_FILE: {"[[red,blue]] car"}}
        assert Concepts._check_concept_exists("green bike", existing, "other.txt") == []

    def test_a_template_ranks_by_its_best_expansion(self):
        """``blue car`` starts one expansion, so it ranks above a mid-line match."""
        existing = {COLORS_FILE: {"a blue car", "[[red,blue]] car"}}
        matches = Concepts._check_concept_exists("blue car", existing, "other.txt")
        assert matches[0] == ("[[red,blue]] car", COLORS_FILE)


# ---------------------------------------------------------------------------
# Concepts.find_blacklist_violation
# ---------------------------------------------------------------------------

class TestFindBlacklistViolation:
    def test_a_blacklisted_concept_is_reported(self):
        item = BlacklistItem("blocked")
        Blacklist.add_item(item)
        assert Concepts.find_blacklist_violation("blocked word", COLORS_FILE) is item

    def test_a_clean_concept_is_not_reported(self):
        Blacklist.add_item(BlacklistItem("blocked"))
        assert Concepts.find_blacklist_violation("fine word", COLORS_FILE) is None

    def test_a_template_is_checked_in_each_expansion(self):
        Blacklist.add_item(BlacklistItem("blocked"))
        assert Concepts.find_blacklist_violation("[[fine,blocked]] word", COLORS_FILE) is not None

    def test_a_disabled_item_is_ignored(self):
        Blacklist.add_item(BlacklistItem("blocked", enabled=False))
        assert Concepts.find_blacklist_violation("blocked word", COLORS_FILE) is None

    def test_a_whole_prompt_item_is_ignored(self):
        """The generation-time concept filter skips these too."""
        Blacklist.add_item(BlacklistItem("blocked", apply_to_whole_prompt=True))
        assert Concepts.find_blacklist_violation("blocked word", COLORS_FILE) is None

    def test_an_nsfw_file_is_exempt_while_the_blacklist_allows_nsfw(self):
        Blacklist.add_item(BlacklistItem("blocked"))
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
        assert Concepts.find_blacklist_violation("blocked word", NSFW.concepts) is None

    def test_an_nsfw_file_is_checked_while_the_blacklist_disallows(self):
        Blacklist.add_item(BlacklistItem("blocked"))
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.DISALLOW
        assert Concepts.find_blacklist_violation("blocked word", NSFW.concepts) is not None

    def test_an_sfw_file_is_checked_even_while_the_blacklist_allows_nsfw(self):
        Blacklist.add_item(BlacklistItem("blocked"))
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
        assert Concepts.find_blacklist_violation("blocked word", COLORS_FILE) is not None


# ---------------------------------------------------------------------------
# Concepts.import_concepts and the blacklist
# ---------------------------------------------------------------------------

class TestImportBlacklisted:
    @pytest.fixture(autouse=True)
    def _blacklist(self):
        Blacklist.add_item(BlacklistItem("blocked"))

    def test_without_a_callback_blacklisted_lines_are_withheld(self, concepts_dir):
        path = write_import(concepts_dir, "crimson", "blocked word")
        imported, failed = Concepts.import_concepts(path, COLORS_FILE)
        assert imported == ["crimson"]
        assert failed == ["blocked word"]
        assert "blocked word" not in read_concepts(concepts_dir / COLORS_FILE)

    def test_a_declined_confirmation_withholds_them(self, concepts_dir):
        path = write_import(concepts_dir, "blocked word")
        Concepts.import_concepts(path, COLORS_FILE, confirm_blacklisted=lambda concepts: False)
        assert "blocked word" not in read_concepts(concepts_dir / COLORS_FILE)

    def test_an_accepted_confirmation_imports_them(self, concepts_dir):
        path = write_import(concepts_dir, "blocked word")
        imported, _failed = Concepts.import_concepts(
            path, COLORS_FILE, confirm_blacklisted=lambda concepts: True
        )
        assert imported == ["blocked word"]
        assert "blocked word" in read_concepts(concepts_dir / COLORS_FILE)

    def test_the_callback_is_asked_once_with_every_hit_sorted(self, concepts_dir):
        calls = []
        path = write_import(concepts_dir, "crimson", "zz blocked", "blocked word")
        Concepts.import_concepts(
            path, COLORS_FILE, confirm_blacklisted=lambda concepts: calls.append(concepts)
        )
        assert calls == [["blocked word", "zz blocked"]]

    def test_the_callback_is_not_asked_when_nothing_is_blacklisted(self, concepts_dir):
        calls = []
        path = write_import(concepts_dir, "crimson")
        Concepts.import_concepts(
            path, COLORS_FILE, confirm_blacklisted=lambda concepts: calls.append(concepts)
        )
        assert calls == []

    def test_force_import_does_not_bypass_the_blacklist(self, concepts_dir):
        path = write_import(concepts_dir, "!blocked word")
        _imported, failed = Concepts.import_concepts(path, COLORS_FILE)
        assert failed == ["blocked word"]

    def test_the_failure_report_does_not_name_the_blacklist_item(self, concepts_dir):
        """Revealing blacklist contents is its own password-protected action."""
        Blacklist.TAG_BLACKLIST.clear()
        Blacklist.add_item(BlacklistItem(r"secret\w*", use_regex=True))
        path = write_import(concepts_dir, "secretive word")
        Concepts.import_concepts(path, COLORS_FILE)
        report = (concepts_dir / "to_import_failed_import.txt").read_text(encoding="utf-8")
        assert "secretive word" in report
        assert r"secret\w*" not in report
