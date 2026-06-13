import os
import pytest
from sd_runner.control_nets import get_control_nets
from sd_runner.ip_adapters import get_ip_adapters


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
