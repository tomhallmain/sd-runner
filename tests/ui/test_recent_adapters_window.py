"""Recent adapters browser: the three per-kind tabs.

ControlNet, IP Adapter and Source Prompt tabs share one implementation and
differ only in what they list and where a pick goes, so each assertion here
runs against all three. The rows are cached on the class, one attribute per
kind, so a cache is also checked to belong to its own tab alone.
"""

import pytest

from lib.translations import I18N
from sd_runner.models.recent_adapters_state import RecentAdaptersState
from sd_runner.ui.models.recent_adapters_window import RecentAdaptersWindow
from tests.utils import close_window

_ = I18N._

# key, tab index, state list, file name, expected type column, file header
KINDS = [
    ("controlnet", 0, "_recent_controlnets", "canny_edge.png", "Canny", "ControlNet File"),
    ("ipadapter", 1, "_recent_ipadapters", "face_ref.png", "Face", "IP Adapter File"),
    ("source_prompt", 2, "_recent_source_prompts", "source.png", None, "Source Prompt File"),
]
KIND_IDS = [k[0] for k in KINDS]


class RecordingAppActions:
    def __init__(self):
        self.adapters = []

    def set_adapter_from_adapters_window(self, path, adapter_type="controlnet", replace=True, is_controlnet=None):
        self.adapters.append((path, adapter_type, replace))

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def files(tmp_path):
    """One real file per kind, each listed as that kind's only recent entry."""
    paths = {}
    for key, _tab, state_attr, name, _type, _header in KINDS:
        path = tmp_path / name
        path.write_bytes(b"")
        setattr(RecentAdaptersState, state_attr, [str(path)])
        paths[key] = str(path)
    return paths


@pytest.fixture
def window(qapp, files):
    actions = RecordingAppActions()
    win = RecentAdaptersWindow(None, actions)
    win._test_actions = actions
    try:
        yield win
    finally:
        close_window(win)


def rows(tree):
    return [
        [tree.topLevelItem(i).text(c) for c in range(tree.columnCount())]
        for i in range(tree.topLevelItemCount())
    ]


@pytest.mark.parametrize("key, tab, state_attr, name, type_label, header", KINDS, ids=KIND_IDS)
def test_tab_lists_its_own_recent_files(window, files, key, tab, state_attr, name, type_label, header):
    tree = window._trees[key]
    assert window._tabs.widget(tab).isAncestorOf(tree)
    assert tree.headerItem().text(0) == _(header)
    [[path, shown_type, _created]] = rows(tree)
    assert path == files[key]
    assert shown_type == (type_label if type_label else _("Source Prompt"))


@pytest.mark.parametrize("key", KIND_IDS)
def test_filter_narrows_the_list(window, key):
    window._filters[key].setText("no-such-file")
    assert rows(window._trees[key]) == []
    window._filters[key].setText("")
    assert len(rows(window._trees[key])) == 1


@pytest.mark.parametrize("replace", [True, False], ids=["replace", "add"])
@pytest.mark.parametrize("key, tab, state_attr, name, type_label, header", KINDS, ids=KIND_IDS)
def test_selecting_sends_the_path_to_its_field(window, files, key, tab, state_attr, name, type_label, header, replace):
    other = files[key] + ".older"
    with open(other, "wb"):
        pass
    getattr(RecentAdaptersState, state_attr).append(other)
    tree = window._trees[key]
    actions = window._test_actions

    kind = next(k for k in window._kinds if k.key == key)
    tree.setCurrentItem(tree.topLevelItem(0))
    selected = tree.selectedItems()[0].text(0)
    window._select_kind(kind, replace=replace)

    assert actions.adapters == [(selected, key, replace)]
    assert getattr(RecentAdaptersState, state_attr)[0] == selected


@pytest.mark.parametrize("key", KIND_IDS)
def test_selecting_nothing_does_nothing(window, key):
    kind = next(k for k in window._kinds if k.key == key)
    window._select_kind(kind)
    assert window._test_actions.adapters == []


@pytest.mark.parametrize("key, tab, state_attr, name, type_label, header", KINDS, ids=KIND_IDS)
def test_refresh_rebuilds_from_state(window, files, tmp_path, key, tab, state_attr, name, type_label, header):
    added = tmp_path / ("new_" + name)
    added.write_bytes(b"")
    getattr(RecentAdaptersState, state_attr).append(str(added))
    kind = next(k for k in window._kinds if k.key == key)

    # The cached rows stand until the cache is dropped.
    window._refresh_kind(kind)
    assert [row[0] for row in rows(window._trees[key])] == [files[key]]

    window._refresh_cache()
    assert sorted(row[0] for row in rows(window._trees[key])) == sorted([files[key], str(added)])


def test_each_kind_caches_under_its_own_attribute(window, files):
    cached = {
        "controlnet": RecentAdaptersWindow._controlnet_cache,
        "ipadapter": RecentAdaptersWindow._ipadapter_cache,
        "source_prompt": RecentAdaptersWindow._source_prompt_cache,
    }
    assert {key: [row[0] for row in rows_] for key, rows_ in cached.items()} == {
        key: [path] for key, path in files.items()
    }


def test_cache_status_is_shown_on_every_kind_tab(window):
    texts = {label.text() for label in window._cache_labels.values()}
    assert len(window._cache_labels) == 3
    [text] = texts
    assert text.startswith(_("Cache") + ":")
    assert _("Not loaded") not in text
