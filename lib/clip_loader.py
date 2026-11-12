"""Load an OpenAI ``clip`` package model with or without TorchScript.

OpenAI's weights are TorchScript archives. With TorchScript disabled
(``PYTORCH_JIT=0``, or Nuitka's ``torch-disable-jit``), ``torch.jit.load`` fails
because ``RecursiveScriptModule`` has no ``_construct``. The state dict is then
read from the C++ module and the model built from it, which is what
``clip.load(jit=False)`` does with the archive anyway.

``clip`` and ``torch`` are passed in, so importing this module imports neither.
"""

from __future__ import annotations

import os


def _script_module_state_dict(torch, cpp_module, prefix: str = "") -> dict:
    state_dict = {}
    for name, tensor in torch._C.ParameterDict(cpp_module).items():
        state_dict[prefix + name] = tensor
    for name, tensor in torch._C.BufferDict(cpp_module).items():
        if tensor is not None:
            state_dict[prefix + name] = tensor
    for name, child in torch._C.ModuleDict(cpp_module).items():
        state_dict.update(_script_module_state_dict(torch, child, f"{prefix}{name}."))
    return state_dict


def torchscript_available(torch) -> bool:
    return hasattr(torch.jit.RecursiveScriptModule, "_construct")


def load_clip_file(clip, torch, model_path: str, device: str):
    """Model and preprocess from a ``.pt`` file, as ``clip.load(jit=False)`` returns them."""
    if torchscript_available(torch):
        return clip.load(model_path, device=device, jit=False)
    from clip.clip import _transform  # noqa: PLC0415
    from clip.model import build_model  # noqa: PLC0415
    try:
        cpp_module = torch._C.import_ir_module(
            torch._C.CompilationUnit(), model_path, torch.device("cpu"), {}, False)
        state_dict = _script_module_state_dict(torch, cpp_module)
    except RuntimeError:
        # Not a TorchScript archive: a plain saved state dict.
        state_dict = torch.load(model_path, map_location="cpu")
    model = build_model(state_dict).to(device)
    if str(device) == "cpu":
        model.float()
    return model, _transform(model.visual.input_resolution)


def load_clip(clip, torch, name: str, device: str):
    """Model and preprocess for a ``.pt`` file or a ``clip`` model name (``"ViT-B/32"``).

    A name is resolved the way ``clip.load`` resolves it, downloading the
    weights to ``~/.cache/clip`` if they are not there yet.
    """
    if os.path.isfile(name):
        return load_clip_file(clip, torch, name, device)
    if torchscript_available(torch):
        return clip.load(name, device=device, jit=False)
    from clip.clip import _MODELS, _download  # noqa: PLC0415
    if name not in _MODELS:
        raise RuntimeError(f"Model {name} not found; available models = {clip.available_models()}")
    return load_clip_file(clip, torch, _download(_MODELS[name], os.path.expanduser("~/.cache/clip")), device)
