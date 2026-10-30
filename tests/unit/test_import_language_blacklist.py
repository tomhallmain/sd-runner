"""Tests for the accept-file tool, and for the curated lists themselves."""

import importlib.util
import os

import pytest

from sd_runner.prompts.blacklist import BlacklistItem

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIST_DIR = os.path.join(REPO_ROOT, "docs", "Sperrliste-Verbesserungen")
ACCEPT_DIR = os.path.join(LIST_DIR, "accept_lists")
BASE_LIST = os.path.join(LIST_DIR, "Sperrlisteausfuhr.csv")
SOURCE_DIR = os.path.join(LIST_DIR, "List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words")


@pytest.fixture(scope="module")
def tool():
    path = os.path.join(REPO_ROOT, "scripts", "import_language_blacklist.py")
    spec = importlib.util.spec_from_file_location("import_language_blacklist", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_accept(tmp_path, *lines):
    path = tmp_path / "accept_de.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestSourceFiles:
    def test_a_regional_list_merges_into_its_language(self, tool, tmp_path):
        for name in ("fr", "fr-CA-u-sd-caqc", "de", "README.md", "LICENSE"):
            (tmp_path / name).write_text("x\n", encoding="utf-8")
        found = [os.path.basename(path) for path in tool.source_files(str(tmp_path), "fr")]
        assert found == ["fr", "fr-CA-u-sd-caqc"]


class TestParsing:
    @pytest.mark.parametrize("line", ["", "   ", "# a comment", "# hold: a, b - reason"])
    def test_blanks_and_comments_give_nothing(self, tool, line):
        assert tool.parse_entry(line) is None

    def test_markers_are_separated_from_the_row(self, tool):
        assert tool.parse_entry("!~pizd") == ({"!", "~"}, "pizd")

    def test_a_hold_line_names_its_entries(self, tool):
        assert tool.parse_holds("# hold: Bonze, mufti - insults") == ["bonze", "mufti"]

    def test_another_comment_holds_nothing(self, tool):
        assert tool.parse_holds("# a comment") == []


class TestBuildItem:
    def test_a_plain_row_takes_the_language_and_a_boundary(self, tool):
        item = tool.build_item(set(), "arsch", "de")
        assert (item.language, item.use_word_boundary, item.use_regex) == ("de", True, False)

    def test_regex_syntax_makes_a_regex_row(self, tool):
        assert tool.build_item(set(), "bl[u]t", "de").use_regex is True

    def test_tilde_removes_the_boundary(self, tool):
        assert tool.build_item({"~"}, "fotze", "de").use_word_boundary is False

    def test_at_makes_a_user_prompts_only_row(self, tool):
        assert tool.build_item({"@"}, "brust", "de").apply_to_generated is False

    def test_bang_makes_a_global_row(self, tool):
        assert tool.build_item({"!"}, "nigger", "de").language is None

    def test_a_no_space_row_gets_no_boundary(self, tool):
        assert tool.build_item(set(), "鸡巴", "zh").use_word_boundary is False


class TestProcessLanguage:
    def test_a_string_already_global_is_skipped(self, tool, tmp_path):
        path = write_accept(tmp_path, "wort")
        items, skipped, _held = tool.process_language("de", path, [BlacklistItem("wort")])
        assert items == []
        assert skipped == [("wort", "already global")]

    def test_a_retag_keeps_the_rows_settings(self, tool, tmp_path):
        base = BlacklistItem("puta($|\\W|s)", use_regex=True)
        items, _skipped, _held = tool.process_language("es", write_accept(tmp_path, "=puta($|\\W|s)"), [base])
        assert items[0].language == "es"
        assert items[0].use_regex is True

    def test_a_retag_with_bang_makes_the_row_global(self, tool, tmp_path):
        base = BlacklistItem("puta($|\\W|s)", use_regex=True)
        items, _skipped, _held = tool.process_language("es", write_accept(tmp_path, "=!puta($|\\W|s)"), [base])
        assert items[0].language is None

    def test_a_retag_of_a_missing_row_is_an_error(self, tool, tmp_path):
        with pytest.raises(ValueError):
            tool.process_language("es", write_accept(tmp_path, "=gone"), [])

    def test_a_plain_row_the_list_catches_is_skipped(self, tool, tmp_path):
        items, skipped, _held = tool.process_language("de", write_accept(tmp_path, "penisse"), [BlacklistItem("penis")])
        assert items == []
        assert skipped == [("penisse", "already caught")]

    def test_a_no_boundary_row_stays_though_the_word_is_caught(self, tool, tmp_path):
        items, _skipped, _held = tool.process_language("de", write_accept(tmp_path, "~penis"), [BlacklistItem("pen")])
        assert len(items) == 1


@pytest.fixture(scope="module")
def lists(tool):
    if not os.path.isdir(ACCEPT_DIR):
        pytest.skip("the accept lists are not in this checkout")
    rows = {}
    for name in sorted(os.listdir(ACCEPT_DIR)):
        language = name[len("accept_"):-len(".txt")]
        with open(os.path.join(ACCEPT_DIR, name), encoding="utf-8") as f:
            entries = [tool.parse_entry(line) for line in f]
        rows[language] = [tool.build_item(*entry, language) for entry in entries if entry and "=" not in entry[0]]
    return rows


class TestCuratedLists:
    def test_every_in_scope_language_has_a_list(self, lists):
        assert set(lists) == {
            "ar", "cs", "da", "de", "eo", "es", "fa", "fi", "fil", "fr", "hi", "hu", "it",
            "ja", "ko", "nl", "no", "pl", "pt", "ru", "sv", "th", "tr", "zh",
        }

    def test_every_source_entry_is_covered_or_held(self, tool, lists):
        if not os.path.isfile(BASE_LIST) or not os.path.isdir(SOURCE_DIR):
            pytest.skip("the source lists are not in this checkout")
        base = tool.load_rows(BASE_LIST)
        global_items = [item for items in lists.values() for item in items if item.language is None]
        missing = {}
        for language in lists:
            path = os.path.join(ACCEPT_DIR, f"accept_{language}.txt")
            items, _skipped, held = tool.process_language(language, path, base)
            found = tool.unreviewed(tool.source_files(SOURCE_DIR, language), items + global_items, base, held)
            if found:
                missing[language] = found
        assert missing == {}

    def test_no_row_is_in_two_languages(self, lists):
        seen = {}
        for language, items in lists.items():
            for item in items:
                assert seen.setdefault(item.string, language) == language, item.string

    @pytest.mark.parametrize("language, text", [
        ("de", "Blüte"), ("de", "Schreibtischlampen"), ("de", "Wunder"), ("de", "Mordor"),
        ("de", "Verwunderung"), ("de", "Schwanzmeise"), ("de", "Marsch"), ("de", "Barsch"),
        ("es", "cono"),
        ("fr", "cul-de-sac"), ("fr", "niquel"),
        ("ja", "ピエロ"), ("ja", "ファックス"), ("ja", "フェラーリ"), ("ja", "ジョコビッチ"),
        ("ja", "グローバル"), ("ja", "カント"), ("ja", "裸足"), ("ja", "逃げろ"),
        ("ko", "자위대"), ("ko", "씹다"), ("ko", "에로스"),
        ("ru", "колебать"), ("ru", "разгребать"), ("ru", "застрахуй"), ("ru", "мандарин"),
        ("ru", "педикюр"), ("ru", "тебе"), ("ru", "застрахую"),
        ("no", "fitted"), ("pl", "Jebusite"), ("fi", "Manussiha"), ("fi", "lapillus"), ("da", "Luderick"),
        ("nl", "strontium"), ("nl", "kutjera"), ("hi", "chinking"),
        ("ar", "كسر"), ("ar", "مصر"), ("cs", "špičatý"), ("eo", "perfekt"), ("eo", "defekto"),
        ("fa", "اکنون"), ("fi", "persecute"), ("fi", "persevere"), ("hi", "कालंड"), ("hi", "लंडन"),
        ("hu", "szarvas"), ("nl", "hoera"), ("nl", "aftrekken"), ("sv", "fitting"), ("sv", "Pitt"),
        ("th", "หีบ"), ("th", "ขี้เกียจ"), ("th", "ควาย"), ("tr", "Goethe"), ("tr", "am"),
        ("zh", "操作"), ("zh", "体操"), ("zh", "日本"), ("zh", "干净"), ("zh", "今日你好"), ("zh", "注射你"),
    ])
    def test_an_ordinary_word_passes(self, lists, language, text):
        assert [item.string for item in lists[language] if item.matches_tag(text)] == []

    @pytest.mark.parametrize("language, text", [
        ("de", "Arschloch"), ("de", "Drecksfotze"), ("de", "SCHEISSE"), ("de", "Moese"),
        ("de", "Blutbad"), ("de", "Tötung"), ("de", "voegeln"), ("de", "Selbstmord"),
        ("ar", "شرموطة"), ("cs", "mrdat"), ("eo", "fikado"), ("fa", "جنده"), ("fi", "hevonvittu"),
        ("hi", "लंड"), ("hu", "faszfej"), ("nl", "klootzak"), ("no", "ståpikk"), ("pl", "skurwysyn"),
        ("sv", "knulla"), ("th", "เย็ด"), ("tr", "orospu"), ("tr", "SİKTİR"), ("fil", "putang ina"),
        ("es", "coño"), ("fr", "salope"), ("it", "cazzo"), ("pt", "caralho"),
        ("ja", "ファック"), ("ja", "セックス"), ("ja", "全裸"),
        ("ko", "씨발"), ("ko", "자위"), ("ko", "개좆"),
        ("ru", "ебать"), ("ru", "выебать"), ("ru", "пиздец"), ("ru", "похуй"),
        ("zh", "操你妈"), ("zh", "鸡巴"), ("zh", "强奸"), ("zh", "插死你"), ("ru", "на хую вертеть"),
    ])
    def test_a_target_word_is_blocked(self, lists, language, text):
        assert any(item.matches_tag(text) for item in lists[language])
