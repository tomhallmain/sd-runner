#!/usr/bin/env python3
"""Convert a ComfyUI UI template into an API prompt.

Run with the ComfyUI environment's Python, and with the ComfyUI checkout on
PYTHONPATH. The sd_runner environment does not import ComfyUI's nodes.

    set PYTHONPATH=C:\\Users\\tehal\\repos\\_external\\ComfyUI
    C:\\Users\\tehal\\miniconda\\envs\\comfy\\python.exe scripts\\convert_comfy_template.py

Source-image templates usually do not choose a new canvas. Width and height
stay linked to the loaded image (GetImageSize, or the loader itself). This
converter keeps those links. It does not insert a resize, and SD Runner's
set_latent_dimensions leaves a dimension alone when the link traces back to
a source image. Graphs that pick their own size (ResolutionSelector, a plain
latent) are the ones the app may overwrite.

Save nodes are rewritten to the filename prefix the existing ComfyUI prompts
use, ``CUI``. Image search globs ``**/CUI*``, so a template name such as
``Krea2_turbo`` would be missed when the app looks for its own output. A
slash in the prefix is a subdirectory of ComfyUI's output directory.
SaveVideo's own default is ``video/ComfyUI``, and the MiniMax H3 template
uses ``video/MiniMax_H3``, which writes ``output/video/MiniMax_H3_00001_.mp4``.
That directory is kept and the file part becomes ``CUI``, so the video stays
under ``output/video`` and is still named for this app.
"""

import asyncio
import json
import sys

sys.path.insert(0, r"C:\Users\tehal\repos\_external\ComfyUI")

import nodes  # noqa: E402

asyncio.run(nodes.init_builtin_extra_nodes())

_CONTROL = {"fixed", "increment", "decrement", "randomize"}
_SKIP = {"Note", "MarkdownNote", "Reroute"}
_SOCKET_TYPES = {"IMAGE", "MASK", "LATENT", "MODEL", "CLIP", "VAE", "CONDITIONING", "AUDIO", "VIDEO"}


def _debug_widgets():
    from comfy_api.latest._io import WidgetInput

    names = [
        "TextGenerate", "ResolutionSelector", "MiniMaxH3ImageToVideo",
        "BasicScheduler", "RandomNoise", "SaveVideo", "ComfyMathExpression",
        "EmptyFlux2LatentImage", "CreateVideo",
    ]
    for name in names:
        cls = nodes.NODE_CLASS_MAPPINGS.get(name)
        print("==", name)
        if cls is None or not hasattr(cls, "define_schema"):
            print("  no schema")
            continue
        for inp in cls.define_schema().inputs or []:
            parent = getattr(type(inp), "Parent", None)
            print(
                " ", inp.id, "widget", isinstance(inp, WidgetInput),
                "parent", getattr(parent, "__name__", None),
            )


def _input_types_widgets(class_type: str):
    cls = nodes.NODE_CLASS_MAPPINGS.get(class_type)
    if cls is None or not hasattr(cls, "INPUT_TYPES"):
        return None
    spec = cls.INPUT_TYPES()
    names = []
    for group in ("required", "optional"):
        for name, conf in (spec.get(group) or {}).items():
            kind = conf[0] if isinstance(conf, (list, tuple)) else conf
            if isinstance(kind, list) or kind in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                names.append(name)
    return names


def _assign_schema_widgets(schema_inputs, values, assigned, index=0, prefix=""):
    from comfy_api.latest._io import DynamicCombo, WidgetInput

    for inp in schema_inputs or []:
        if index >= len(values):
            return index
        if (getattr(inp, "extra_dict", None) or {}).get("hidden"):
            continue
        if isinstance(inp, DynamicCombo.Input):
            selected = values[index]
            index += 1
            name = f"{prefix}{inp.id}"
            assigned[name] = selected
            option = next((item for item in inp.options if item.key == selected), None)
            if option is not None:
                index = _assign_schema_widgets(option.inputs, values, assigned, index, prefix=f"{name}.")
            continue
        if not isinstance(inp, WidgetInput) or getattr(inp, "force_input", None):
            continue
        parent = getattr(type(inp), "Parent", None)
        if getattr(parent, "__name__", None) == "ResolutionPreview":
            continue
        name = f"{prefix}{inp.id}"
        assigned[name] = values[index]
        index += 1
        if getattr(inp, "control_after_generate", None) and index < len(values) and values[index] in _CONTROL:
            index += 1
    return index


def _widget_values(node):
    values = list(node.get("widgets_values") or [])
    cls = nodes.NODE_CLASS_MAPPINGS.get(node.get("type"))
    if cls is not None and hasattr(cls, "define_schema"):
        assigned = {}
        _assign_schema_widgets(cls.define_schema().inputs or [], values, assigned)
        return assigned
    names = _input_types_widgets(node.get("type"))
    if not names:
        named = node.get("widgets_values_named") or {}
        return {key: value for key, value in named.items() if "." not in str(key)}
    assigned = {}
    index = 0
    for name in names:
        if index >= len(values):
            break
        assigned[name] = values[index]
        index += 1
        if name in {"seed", "noise_seed"} and index < len(values) and values[index] in _CONTROL:
            index += 1
    return assigned


def _normalize_link(link):
    if isinstance(link, dict):
        return [
            link["id"], link["origin_id"], link["origin_slot"],
            link["target_id"], link["target_slot"], link.get("type"),
        ]
    return link


def _index_links(links):
    normalized = [_normalize_link(link) for link in links or []]
    return {link[0]: link for link in normalized}


def _follow_reroute(origin_id, origin_slot, nodes_by_id, links):
    seen = set()
    while origin_id in nodes_by_id and nodes_by_id[origin_id].get("type") == "Reroute":
        if origin_id in seen:
            break
        seen.add(origin_id)
        link_id = None
        for inp in nodes_by_id[origin_id].get("inputs") or []:
            if inp.get("link") is not None:
                link_id = inp["link"]
                break
        if link_id is None or link_id not in links:
            break
        link = links[link_id]
        origin_id, origin_slot = link[1], link[2]
    return origin_id, origin_slot


class Converter:
    def __init__(self, workflow):
        self.workflow = workflow
        self.subgraphs = {sg["id"]: sg for sg in workflow.get("definitions", {}).get("subgraphs", [])}
        self.prompt = {}
        self.missing = set()

    def convert(self):
        nodes_by_id = {node["id"]: node for node in self.workflow.get("nodes", [])}
        links = _index_links(self.workflow.get("links"))
        for node in self.workflow.get("nodes", []):
            self._emit(node, "", nodes_by_id, links, None)
        return self.prompt

    def _emit(self, node, prefix, nodes_by_id, links, outer):
        class_type = node.get("type")
        if class_type in _SKIP:
            return
        if class_type in self.subgraphs:
            self._emit_subgraph(node, prefix, nodes_by_id, links)
            return
        node_id = f"{prefix}{node['id']}"
        inputs = _widget_values(node)
        for inp in node.get("inputs") or []:
            link_id = inp.get("link")
            if link_id is None or link_id not in links:
                continue
            # Keep the link, including a width/height that still points at the
            # source image. Do not replace it with the widget's number.
            source = self._source(links[link_id], nodes_by_id, links, prefix, outer)
            if source is not None:
                inputs[inp["name"]] = source
        if class_type not in nodes.NODE_CLASS_MAPPINGS:
            self.missing.add(class_type)
        self.prompt[node_id] = {
            "inputs": inputs,
            "class_type": class_type,
            "_meta": {"title": node.get("title") or class_type},
        }

    def _emit_subgraph(self, node, prefix, outer_nodes, outer_links):
        sg = self.subgraphs[node["type"]]
        inner_prefix = f"{prefix}{node['id']}:"
        inner_nodes = {item["id"]: item for item in sg.get("nodes", [])}
        inner_links = _index_links(sg.get("links"))
        outer = {"node": node, "nodes": outer_nodes, "links": outer_links, "prefix": prefix, "sg": sg}
        for inner in sg.get("nodes", []):
            self._emit(inner, inner_prefix, inner_nodes, inner_links, outer)

    def _source(self, link, nodes_by_id, links, prefix, outer):
        origin_id, origin_slot = _follow_reroute(link[1], link[2], nodes_by_id, links)
        node = nodes_by_id.get(origin_id)
        if outer is not None and origin_id == outer["sg"].get("inputNode", {}).get("id"):
            return self._subgraph_input(outer["sg"], link[0], outer)
        if node is None or node.get("type") in _SKIP:
            return None
        if node.get("type") in self.subgraphs:
            return self._subgraph_output(node, origin_slot, prefix)
        return [f"{prefix}{origin_id}", origin_slot]

    def _subgraph_input(self, sg, link_id, outer):
        # Image sockets are omitted from widgets_values. Every other subgraph
        # input occupies one slot, and a link on that input wins.
        node = outer["node"]
        widgets = list(node.get("widgets_values") or [])
        widget_index = 0
        outer_by_name = {inp.get("name"): inp for inp in node.get("inputs") or []}
        for spec in sg.get("inputs") or []:
            widget_value = None
            if spec.get("type") not in _SOCKET_TYPES and widget_index < len(widgets):
                widget_value = widgets[widget_index]
                widget_index += 1
            matched = outer_by_name.get(spec.get("name"))
            if matched and matched.get("link") is not None and matched["link"] in outer["links"]:
                value = self._source(
                    outer["links"][matched["link"]], outer["nodes"], outer["links"], outer["prefix"], None,
                )
            elif spec.get("type") in _SOCKET_TYPES:
                value = None
            else:
                value = widget_value
            if link_id in (spec.get("linkIds") or []):
                return value
        return None

    def _subgraph_output(self, node, slot, prefix):
        sg = self.subgraphs[node["type"]]
        outputs = sg.get("outputs") or []
        if slot >= len(outputs):
            return None
        link_ids = outputs[slot].get("linkIds") or []
        if not link_ids:
            return None
        link = _index_links(sg.get("links")).get(link_ids[0])
        if link is None:
            return None
        return [f"{prefix}{node['id']}:{link[1]}", link[2]]


def _prune_unreached(prompt):
    """Keep nodes that feed the saved image or video. Side previews are dropped.

    A LoadImage that sizes the output stays, because that link is on the path
    to the save node. Dropping it would be the resize the template did not ask for.
    """
    outputs = [
        node_id for node_id, node in prompt.items()
        if node["class_type"] in {"SaveImage", "SaveVideo"}
    ]
    keep = set()
    stack = list(outputs)
    while stack:
        node_id = stack.pop()
        if node_id in keep or node_id not in prompt:
            continue
        keep.add(node_id)
        for value in prompt[node_id]["inputs"].values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                stack.append(value[0])
    return {node_id: node for node_id, node in prompt.items() if node_id in keep}


# Sample captions and system prompts shipped in the template. The app writes
# the user's prompt at run time, so these strings would otherwise leak into
# a generation that never set them.
_PROMPT_TEXT_KEYS = {"text", "prompt", "system_prompt", "wildcard_text", "populated_text", "string_a", "string_b"}
_PROMPT_VALUE_NODES = {"PrimitiveStringMultiline", "PrimitiveString", "CLIPTextEncode"}


def _clear_default_text(prompt):
    for node in prompt.values():
        for key, value in node["inputs"].items():
            if not isinstance(value, str) or value == "":
                continue
            if key in _PROMPT_TEXT_KEYS or (key == "value" and node["class_type"] in _PROMPT_VALUE_NODES):
                node["inputs"][key] = ""


def _with_model_folder(name, folder):
    if not isinstance(name, str) or "\\" in name or "/" in name:
        return name
    return folder.rstrip("\\/") + "\\" + name


# Existing ComfyUI prompts save as CUI_00001_.png. Image search globs **/CUI*.
_FILENAME_PREFIX = "CUI"


def _set_filename_prefix(prompt):
    """Point every save node at the CUI prefix, keeping a template subdirectory.

    ``video/MiniMax_H3`` becomes ``video/CUI``. A prefix with no slash becomes
    ``CUI``.
    """
    for node in prompt.values():
        if node["class_type"] not in {"SaveImage", "SaveVideo"}:
            continue
        current = node["inputs"].get("filename_prefix")
        if isinstance(current, str) and ("/" in current or "\\" in current):
            directory = current.replace("\\", "/").rsplit("/", 1)[0]
            node["inputs"]["filename_prefix"] = f"{directory}/{_FILENAME_PREFIX}"
        else:
            node["inputs"]["filename_prefix"] = _FILENAME_PREFIX


def _organize_model_paths(prompt, folder):
    """Diffusion weights and LoRAs live in a family folder.

    Text encoders and VAEs are left as bare filenames. Those two are the
    categories that are not always sorted the same way.
    """
    if not folder:
        return
    for node in prompt.values():
        inputs = node["inputs"]
        class_type = node["class_type"]
        if class_type == "UNETLoader":
            inputs["unet_name"] = _with_model_folder(inputs.get("unet_name"), folder)
        elif class_type in {"LoraLoader", "LoraLoaderModelOnly"}:
            inputs["lora_name"] = _with_model_folder(inputs.get("lora_name"), folder)


def convert_file(src, dest, model_folder=None):
    workflow = json.load(open(src, encoding="utf-8"))
    converter = Converter(workflow)
    prompt = _prune_unreached(converter.convert())
    _clear_default_text(prompt)
    _set_filename_prefix(prompt)
    _organize_model_paths(prompt, model_folder)
    missing_links = []
    for node_id, node in prompt.items():
        for key, value in node["inputs"].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                if value[0] not in prompt:
                    missing_links.append((node_id, key, value[0]))
    json.dump(prompt, open(dest, "w", encoding="utf-8"), indent=2)
    print(dest, "nodes", len(prompt), "missing_types", sorted(converter.missing), "bad_links", missing_links[:8])


if __name__ == "__main__":
    if "--debug-widgets" in sys.argv:
        _debug_widgets()
        raise SystemExit
    root = r"C:\Users\tehal\miniconda\envs\comfy\Lib\site-packages\comfyui_workflow_templates_json\templates"
    out = r"c:\Users\tehal\repos\sd-runner\sd_runner\data\workflows\comfyui"
    pairs = [
        (root + r"\image_krea2_turbo_t2i.json", out + r"\image_krea2_turbo_t2i.json", "Krea2"),
        (root + r"\image_flux3_klein_t2i.json", out + r"\image_flux3_klein_t2i.json", "Flux3"),
        (root + r"\video_minimax_h3_t2v.json", out + r"\video_minimax_h3_t2v.json", "MiniMaxH3"),
    ]
    for src, dest, folder in pairs:
        convert_file(src, dest, folder)
