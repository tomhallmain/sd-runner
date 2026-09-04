import os
import pytest
from sd_runner.models.control_nets import get_control_nets
from sd_runner.models.ip_adapters import get_ip_adapters


@pytest.fixture
def image_dir(tmp_path):
    """Temporary directory with 10 numbered PNG files (control nets are input images)."""
    for i in range(10):
        p = tmp_path / f"img_{i:02d}.png"
        p.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8)
    return str(tmp_path)


class TestAdapterSorting:
    def test_no_app_actions_returns_all_files(self, image_dir):
        control_nets, is_dir = get_control_nets([image_dir], random_sort=False, app_actions=None)
        assert is_dir
        assert len(control_nets) == 10

    def test_alphabetical_order_when_no_recent(self, image_dir, mock_app_actions):
        mock_app_actions.contains_recent_adapter_file.return_value = -1
        control_nets, _ = get_control_nets([image_dir], random_sort=False, app_actions=mock_app_actions)
        names = [os.path.basename(cn.id) for cn in control_nets]
        assert names == sorted(names)

    def test_recent_files_placed_at_end(self, image_dir, mock_app_actions):
        """Files marked as recent should come after non-recent ones."""
        recent_name = "img_03.png"

        def _contains(path):
            return 0 if os.path.basename(path) == recent_name else -1

        mock_app_actions.contains_recent_adapter_file.side_effect = _contains
        control_nets, _ = get_control_nets([image_dir], random_sort=False, app_actions=mock_app_actions)
        names = [os.path.basename(cn.id) for cn in control_nets]
        assert names[-1] == recent_name

    def test_recency_order_least_recent_first(self, image_dir, mock_app_actions):
        """Lower recency index = more recent; least-recent should appear before most-recent."""
        def _contains(path):
            num = int(os.path.basename(path).split('_')[1].split('.')[0])
            return num  # 0 = most recent, 9 = least recent

        mock_app_actions.contains_recent_adapter_file.side_effect = _contains
        control_nets, _ = get_control_nets([image_dir], random_sort=False, app_actions=mock_app_actions)
        names = [os.path.basename(cn.id) for cn in control_nets]
        assert names == [f"img_{i:02d}.png" for i in range(9, -1, -1)]

    def test_ip_adapters_same_sorting_logic(self, image_dir, mock_app_actions):
        mock_app_actions.contains_recent_adapter_file.return_value = -1
        ip_adapters, is_dir = get_ip_adapters([image_dir], random_sort=False, app_actions=mock_app_actions)
        assert is_dir
        assert len(ip_adapters) == 10

    def test_empty_directory(self, tmp_path, mock_app_actions):
        control_nets, is_dir = get_control_nets([str(tmp_path)], random_sort=False, app_actions=mock_app_actions)
        assert is_dir
        assert len(control_nets) == 0
        mock_app_actions.contains_recent_adapter_file.assert_not_called()


# ---------------------------------------------------------------------------
# LazyAdapterList — list compatibility and actual laziness
#
# The lazy list only pays off if callers avoid touching every element. Two
# places used to defeat that by filtering the whole list through is_valid(),
# and GenConfig.prepare() needs list mutation the wrapper did not implement.
# ---------------------------------------------------------------------------

class TestLazyAdapterList:
    def _lazy(self, count=5):
        from sd_runner.models.adapter_sorting import LazyAdapterList
        built = []

        def factory(path):
            built.append(path)
            return f"adapter:{path}"

        return LazyAdapterList([f"p{i}" for i in range(count)], factory), built

    def test_len_constructs_nothing(self):
        lazy, built = self._lazy()
        assert len(lazy) == 5
        assert built == []

    def test_bool_constructs_nothing(self):
        lazy, built = self._lazy()
        assert bool(lazy) is True
        assert built == []

    def test_indexing_constructs_only_that_item(self):
        lazy, built = self._lazy()
        lazy[2]
        assert built == ["p2"]

    def test_repeated_access_constructs_once(self):
        lazy, built = self._lazy()
        lazy[2]
        lazy[2]
        assert built == ["p2"]

    def test_negative_index_works(self):
        lazy, _built = self._lazy()
        assert lazy[-1] == "adapter:p4"

    def test_slice_returns_a_plain_list(self):
        lazy, built = self._lazy()
        assert lazy[:2] == ["adapter:p0", "adapter:p1"]
        assert built == ["p0", "p1"]

    def test_iteration_constructs_everything(self):
        lazy, built = self._lazy()
        list(lazy)
        assert len(built) == 5

    def test_empty_list_is_falsy(self):
        from sd_runner.models.adapter_sorting import LazyAdapterList
        assert not LazyAdapterList([], lambda p: p)


class TestLazyAdapterListMutation:
    """GenConfig.prepare() pads and clears these lists; both must work."""

    def test_append_to_empty_list(self):
        from sd_runner.models.adapter_sorting import LazyAdapterList
        lazy = LazyAdapterList([], lambda p: p)
        lazy.append(None)
        assert len(lazy) == 1
        assert lazy[0] is None

    def test_appended_item_is_returned_as_given(self):
        from sd_runner.models.adapter_sorting import LazyAdapterList
        lazy = LazyAdapterList(["p0"], lambda p: f"adapter:{p}")
        lazy.append(None)
        assert lazy[1] is None
        assert lazy[0] == "adapter:p0"

    def test_clear_empties_the_list(self):
        from sd_runner.models.adapter_sorting import LazyAdapterList
        lazy = LazyAdapterList(["p0", "p1"], lambda p: p)
        lazy.clear()
        assert len(lazy) == 0

    def test_clear_then_append_matches_the_redo_branch(self):
        from sd_runner.models.adapter_sorting import LazyAdapterList
        lazy = LazyAdapterList(["p0", "p1"], lambda p: p)
        lazy.clear()
        lazy.append(None)
        assert len(lazy) == 1
        assert lazy[0] is None

    def test_gen_config_prepare_accepts_a_lazy_list(self):
        """Regression: prepare() raised AttributeError on a lazy adapter list."""
        from sd_runner.models.adapter_sorting import LazyAdapterList
        from tests.utils import make_gen_config

        config = make_gen_config(
            control_nets=LazyAdapterList([], lambda p: p),
            ip_adapters=LazyAdapterList([], lambda p: p),
        )
        config.prepare()
        assert len(config.control_nets) == 1
        assert config.control_nets[0] is None
        assert config.ip_adapters[0] is None
