"""Spelling file inputs the way ComfyUI lists them.

ComfyUI validates a filename against its list as an exact string. A template
naming ``MiniMaxH3\\...`` must still run against a folder named ``MinimaxH3``.
"""

from sd_runner.generators.comfy import ComfyGen

LORA = "MinimaxH3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
OTHER_LORA = "Krea2\\krea2_darkbrush.safetensors"


def _lists(options):
    calls = []

    def listed(class_type):
        calls.append(class_type)
        return options.get(class_type, {})

    return listed, calls


def _lora_node(name):
    return {"class_type": "LoraLoaderModelOnly", "inputs": {"lora_name": name, "strength_model": 1}}


def test_a_case_difference_takes_the_listed_spelling():
    workflow = {"1": _lora_node("MiniMaxH3\\minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors")}
    listed, _ = _lists({"LoraLoaderModelOnly": {"lora_name": [OTHER_LORA, LORA]}})
    ComfyGen.match_listed_filenames(workflow, listed)
    assert workflow["1"]["inputs"]["lora_name"] == LORA


def test_slash_direction_is_also_matched():
    workflow = {"1": _lora_node("minimaxh3/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors")}
    listed, _ = _lists({"LoraLoaderModelOnly": {"lora_name": [LORA]}})
    ComfyGen.match_listed_filenames(workflow, listed)
    assert workflow["1"]["inputs"]["lora_name"] == LORA


def test_a_listed_value_is_unchanged():
    workflow = {"1": _lora_node(LORA)}
    listed, _ = _lists({"LoraLoaderModelOnly": {"lora_name": [LORA]}})
    ComfyGen.match_listed_filenames(workflow, listed)
    assert workflow["1"]["inputs"]["lora_name"] == LORA


def test_a_missing_file_is_left_for_comfyui_to_report():
    workflow = {"1": _lora_node("MiniMaxH3\\not_downloaded.safetensors")}
    listed, _ = _lists({"LoraLoaderModelOnly": {"lora_name": [LORA]}})
    ComfyGen.match_listed_filenames(workflow, listed)
    assert workflow["1"]["inputs"]["lora_name"] == "MiniMaxH3\\not_downloaded.safetensors"


def test_two_candidates_are_left_alone():
    workflow = {"1": _lora_node("a\\x.safetensors")}
    listed, _ = _lists({"LoraLoaderModelOnly": {"lora_name": ["A\\x.safetensors", "a/X.safetensors"]}})
    ComfyGen.match_listed_filenames(workflow, listed)
    assert workflow["1"]["inputs"]["lora_name"] == "a\\x.safetensors"


def test_an_unreachable_comfyui_leaves_the_prompt_as_it_was():
    workflow = {"1": _lora_node("MiniMaxH3\\x.safetensors")}

    def unreachable(class_type):
        raise OSError("connection refused")

    ComfyGen.match_listed_filenames(workflow, unreachable)
    assert workflow["1"]["inputs"]["lora_name"] == "MiniMaxH3\\x.safetensors"


def test_each_node_type_is_looked_up_once():
    workflow = {"1": _lora_node("a.safetensors"), "2": _lora_node("b.safetensors")}
    listed, calls = _lists({"LoraLoaderModelOnly": {"lora_name": ["A.safetensors", "B.safetensors"]}})
    ComfyGen.match_listed_filenames(workflow, listed)
    assert calls == ["LoraLoaderModelOnly"]
    assert workflow["2"]["inputs"]["lora_name"] == "B.safetensors"
