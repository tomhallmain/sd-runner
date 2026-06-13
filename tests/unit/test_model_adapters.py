import pytest
from sd_runner.model_adapters import ControlNet, IPAdapter
from utils.globals import Globals


def abs_path(tmp_path, name):
    """Return an absolute path string under tmp_path."""
    return str(tmp_path / name)


class TestIPAdapterConstruction:
    def test_absolute_path_stored_directly(self, tmp_path):
        path = abs_path(tmp_path, "image.jpg")
        adapter = IPAdapter(id=path)
        assert adapter.id == path

    def test_generation_path_matches_id_initially(self, tmp_path):
        path = abs_path(tmp_path, "image.jpg")
        adapter = IPAdapter(id=path)
        assert adapter.generation_path == adapter.id

    def test_default_strength_from_globals(self, tmp_path):
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"))
        assert adapter.strength == Globals.DEFAULT_IPADAPTER_STRENGTH

    def test_explicit_strength_stored(self, tmp_path):
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"), strength=0.75)
        assert adapter.strength == 0.75

    def test_empty_id_stored_directly(self):
        adapter = IPAdapter(id="")
        assert adapter.id == ""


class TestIPAdapterValidity:
    def test_is_valid_false_for_nonexistent_file(self, tmp_path):
        adapter = IPAdapter(id=abs_path(tmp_path, "missing.jpg"))
        assert adapter.is_valid() is False

    def test_is_valid_true_for_existing_file(self, tmp_path):
        p = tmp_path / "real.jpg"
        p.write_bytes(b"\xff\xd8\xff")  # minimal JPEG header bytes
        adapter = IPAdapter(id=str(p))
        assert adapter.is_valid() is True


class TestIPAdapterBWColorationModifier:
    def test_no_bw_desc_returns_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(IPAdapter, "B_W_COLORATION", "sepia tones")
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"), desc="colour photo")
        result = adapter.b_w_coloration_modifier("a portrait")
        assert result == "a portrait"

    def test_bw_desc_appends_coloration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(IPAdapter, "B_W_COLORATION", "warm sepia")
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"), desc="b & w vintage")
        result = adapter.b_w_coloration_modifier("a portrait")
        assert result == "a portrait, warm sepia"

    def test_bw_desc_no_coloration_set_calls_mix_colors(self, tmp_path, monkeypatch):
        monkeypatch.setattr(IPAdapter, "B_W_COLORATION", "")
        # Mock GlobalPrompter.prompter_instance.mix_colors to avoid None dereference
        from sd_runner.prompter import GlobalPrompter

        class FakePrompter:
            def mix_colors(self):
                return "golden yellow"

        monkeypatch.setattr(GlobalPrompter, "prompter_instance", FakePrompter())
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"), desc="b & w photo")
        result = adapter.b_w_coloration_modifier("portrait")
        assert result == "portrait, golden yellow"


class TestIPAdapterStr:
    def test_str_with_desc_and_modifiers(self, tmp_path):
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"), desc="portrait", modifiers="soft", strength=0.5)
        s = str(adapter)
        assert "portrait" in s and "soft" in s and "0.5" in s

    def test_str_with_desc_no_modifiers(self, tmp_path):
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"), desc="portrait", strength=0.5)
        s = str(adapter)
        assert "portrait" in s and "0.5" in s

    def test_str_minimal(self, tmp_path):
        adapter = IPAdapter(id=abs_path(tmp_path, "img.jpg"), strength=0.3)
        s = str(adapter)
        assert "0.3" in s


class TestIPAdapterEquality:
    def test_equal_same_id(self, tmp_path):
        path = abs_path(tmp_path, "img.jpg")
        a = IPAdapter(id=path)
        b = IPAdapter(id=path)
        assert a == b

    def test_not_equal_different_id(self, tmp_path):
        a = IPAdapter(id=abs_path(tmp_path, "a.jpg"))
        b = IPAdapter(id=abs_path(tmp_path, "b.jpg"))
        assert a != b

    def test_not_equal_to_non_adapter(self, tmp_path):
        a = IPAdapter(id=abs_path(tmp_path, "img.jpg"))
        assert a != "not an adapter"

    def test_hash_equal_for_same_id(self, tmp_path):
        path = abs_path(tmp_path, "img.jpg")
        a = IPAdapter(id=path)
        b = IPAdapter(id=path)
        assert hash(a) == hash(b)


class TestControlNetConstruction:
    def test_id_stored(self, tmp_path):
        path = abs_path(tmp_path, "depth.png")
        cn = ControlNet(id=path)
        assert cn.id == path

    def test_default_strength(self, tmp_path):
        cn = ControlNet(id=abs_path(tmp_path, "depth.png"))
        assert cn.strength == Globals.DEFAULT_CONTROL_NET_STRENGTH


class TestControlNetValidity:
    def test_is_valid_false_for_nonexistent_file(self, tmp_path):
        cn = ControlNet(id=abs_path(tmp_path, "missing.png"))
        assert cn.is_valid() is False

    def test_is_valid_true_for_existing_file(self, tmp_path):
        p = tmp_path / "edge.png"
        p.write_bytes(b"\x89PNG")
        cn = ControlNet(id=str(p))
        assert cn.is_valid() is True


class TestControlNetEquality:
    def test_equal_same_id(self, tmp_path):
        path = abs_path(tmp_path, "cn.png")
        a = ControlNet(id=path)
        b = ControlNet(id=path)
        assert a == b
        assert not (a != b)

    def test_not_equal_different_id(self, tmp_path):
        a = ControlNet(id=abs_path(tmp_path, "a.png"))
        b = ControlNet(id=abs_path(tmp_path, "b.png"))
        assert a != b

    def test_hash_same_for_equal(self, tmp_path):
        path = abs_path(tmp_path, "cn.png")
        a = ControlNet(id=path)
        b = ControlNet(id=path)
        assert hash(a) == hash(b)
