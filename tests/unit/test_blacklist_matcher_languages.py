"""Matching outside English: German transliteration and no-space scripts."""

import csv

import pytest

from sd_runner.prompts.blacklist import Blacklist, BlacklistItem


class TestTransliteration:
    @pytest.mark.parametrize("row, text", [
        ("möse", "Möse"),
        ("möse", "Moese"),
        ("scheiße", "scheiße"),
        ("scheiße", "scheisse"),
        ("scheiße", "SCHEISSE"),
        ("mädchen", "Maedchen"),
        ("brüste", "Brueste"),
    ])
    def test_a_plain_row_matches_both_spellings(self, row, text):
        assert BlacklistItem(row, use_word_boundary=False).matches_tag(text)

    def test_a_longer_word_sharing_the_stem_does_not_match(self):
        """Brüstung is a balustrade: the row needs the e that follows its st."""
        assert not BlacklistItem("brüste", use_word_boundary=False).matches_tag("Bruestung")

    def test_a_regex_row_matches_both_spellings(self):
        item = BlacklistItem("m(ä|x)dchen", use_regex=True)
        assert item.matches_tag("Mädchen")
        assert item.matches_tag("Maedchen")

    def test_a_base_letter_still_matches_the_umlaut(self):
        assert BlacklistItem("kuss").matches_tag("Küss")

    def test_a_character_class_is_left_alone(self):
        item = BlacklistItem("bl[u]t", use_regex=True)
        assert item.matches_tag("Blut")
        assert not item.matches_tag("Blüte")

    def test_an_ascii_row_compiles_as_it_did(self):
        assert BlacklistItem("cat").regex_pattern.pattern.endswith("[tþ]")


class TestTurkish:
    @pytest.mark.parametrize("text", ["sik", "SİK", "sık"])
    def test_a_plain_row_matches_every_form_of_i(self, text):
        assert BlacklistItem("sik").matches_tag(text)

    def test_a_quantifier_after_i_applies_to_all_of_it(self):
        item = BlacklistItem("hi?at", use_regex=True)
        assert item.matches_tag("hat")
        assert item.matches_tag("hiat")


class TestLookbehind:
    def test_a_row_with_a_lookbehind_compiles_and_works(self):
        item = BlacklistItem("(?<!ti)schlampe", use_regex=True, use_word_boundary=False)
        assert item.matches_tag("Drecksschlampe")
        assert not item.matches_tag("Schreibtischlampe")

    def test_a_lookahead_is_still_expanded(self):
        item = BlacklistItem("cock(?!tail)", use_regex=True)
        assert not item.matches_tag("cocktail")
        assert not item.matches_tag("cocktaíl")


class TestNoSpaceScripts:
    @pytest.mark.parametrize("row, text", [
        ("鸡巴", "他的鸡巴很大"),
        ("ちんこ", "これはちんこです"),
    ])
    def test_a_boundary_item_matches_mid_sentence(self, row, text):
        assert BlacklistItem(row).matches_tag(text)

    def test_a_regex_row_matches_mid_sentence(self):
        assert BlacklistItem("操(你|妳)", use_regex=True).matches_tag("我操你")

    def test_a_latin_row_keeps_its_boundary(self):
        assert not BlacklistItem("cat").matches_tag("scat")

    def test_hangul_keeps_its_boundary(self):
        assert not BlacklistItem("좆").matches_tag("가좆")

    def test_the_stored_flag_round_trips(self):
        item = BlacklistItem("鸡巴", use_word_boundary=True)
        assert BlacklistItem.from_dict(item.to_dict()).use_word_boundary is True


class TestIneffectiveBoundary:
    def test_a_boundary_on_a_no_space_string_is_flagged(self):
        assert BlacklistItem("鸡巴").has_ineffective_word_boundary() is True

    def test_no_boundary_on_a_no_space_string_is_not(self):
        assert BlacklistItem("鸡巴", use_word_boundary=False).has_ineffective_word_boundary() is False

    def test_a_latin_string_is_not(self):
        assert BlacklistItem("cat").has_ineffective_word_boundary() is False

    def test_the_import_report_names_it(self, tmp_path):
        path = tmp_path / "bl.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["string", "use_word_boundary"])
            writer.writerow(["鸡巴", "True"])
        report = Blacklist.import_blacklist_csv(str(path))
        assert [item.string for item in report.ineffective_boundary] == ["鸡巴"]
