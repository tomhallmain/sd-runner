"""lib/clip_loader.py, driven by stand-ins for the clip and torch modules."""

import sys
import types

import pytest

from lib import clip_loader


class FakeModel:
    def __init__(self, state_dict=None):
        self.state_dict = state_dict
        self.device = None
        self.floated = False
        self.visual = types.SimpleNamespace(input_resolution=224)

    def to(self, device):
        self.device = device
        return self

    def float(self):
        self.floated = True
        return self


def fake_torch(torchscript: bool, ir_module_error: bool = False):
    script_cls = type("RecursiveScriptModule", (), {"_construct": classmethod(lambda c: None)} if torchscript else {})

    def import_ir_module(_cu, path, _device, _extra, _flag):
        if ir_module_error:
            raise RuntimeError("not a TorchScript archive")
        return {"params": {"w": f"tensor:{path}"}, "buffers": {"b": None}, "children": {}}

    c = types.SimpleNamespace(
        CompilationUnit=lambda: object(),
        import_ir_module=import_ir_module,
        ParameterDict=lambda m: m["params"],
        BufferDict=lambda m: m["buffers"],
        ModuleDict=lambda m: m["children"],
    )
    return types.SimpleNamespace(
        jit=types.SimpleNamespace(RecursiveScriptModule=script_cls),
        _C=c,
        device=lambda name: name,
        load=lambda path, map_location=None: {"plain": path},
    )


@pytest.fixture
def fake_clip(monkeypatch):
    calls = []
    clip = types.ModuleType("clip")
    clip.load = lambda name, device=None, jit=None: calls.append((name, device, jit)) or ("model", "pre")
    clip.available_models = lambda: ["ViT-B/32"]
    clip_clip = types.ModuleType("clip.clip")
    clip_clip._transform = lambda res: f"transform:{res}"
    clip_clip._MODELS = {"ViT-B/32": "https://example.invalid/vit.pt"}
    clip_clip._download = lambda url, root: "/cache/vit.pt"
    clip_model = types.ModuleType("clip.model")
    clip_model.build_model = FakeModel
    monkeypatch.setitem(sys.modules, "clip", clip)
    monkeypatch.setitem(sys.modules, "clip.clip", clip_clip)
    monkeypatch.setitem(sys.modules, "clip.model", clip_model)
    clip.calls = calls
    return clip


def test_with_torchscript_uses_clip_load(fake_clip, tmp_path):
    path = tmp_path / "m.pt"
    path.write_bytes(b"")
    assert clip_loader.load_clip_file(fake_clip, fake_torch(True), str(path), "cpu") == ("model", "pre")
    assert fake_clip.calls == [(str(path), "cpu", False)]


def test_without_torchscript_reads_the_archive_state_dict(fake_clip):
    model, preprocess = clip_loader.load_clip_file(fake_clip, fake_torch(False), "/m.pt", "cpu")
    assert model.state_dict == {"w": "tensor:/m.pt"}
    assert model.floated and preprocess == "transform:224"
    assert fake_clip.calls == []


def test_without_torchscript_falls_back_to_a_plain_state_dict(fake_clip):
    model, _pre = clip_loader.load_clip_file(fake_clip, fake_torch(False, ir_module_error=True), "/m.pt", "cuda")
    assert model.state_dict == {"plain": "/m.pt"}
    assert not model.floated


def test_name_without_torchscript_is_resolved_through_the_download_cache(fake_clip):
    model, _pre = clip_loader.load_clip(fake_clip, fake_torch(False), "ViT-B/32", "cpu")
    assert model.state_dict == {"w": "tensor:/cache/vit.pt"}


def test_name_with_torchscript_goes_to_clip_load(fake_clip):
    clip_loader.load_clip(fake_clip, fake_torch(True), "ViT-B/32", "cpu")
    assert fake_clip.calls == [("ViT-B/32", "cpu", False)]


def test_unknown_name_without_torchscript(fake_clip):
    with pytest.raises(RuntimeError):
        clip_loader.load_clip(fake_clip, fake_torch(False), "nope", "cpu")
