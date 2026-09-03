"""The pre-pass that transforms a run's reference image before the run uses it.

Mirrors the second-derivative tests in shape, but the interesting assertions are
different: the pre-pass runs *first*, with its own workflow and prompt, and its
output must reach the user's workflow without disturbing the lineage that names
the user's real source image.

``BaseImageGenerator`` is abstract and its concrete subclasses talk to a
backend, so these drive a stub subclass whose workflows record their arguments
and report paths.
"""

from sd_runner.generators.base import BaseImageGenerator
from sd_runner.model_adapters import ControlNet, IPAdapter
from ui_qt.presets.intermediate_prompt import IntermediatePrompt
from tests.utils import make_gen_config
from utils.globals import WorkflowType


class StubGenerator(BaseImageGenerator):
    """Records every workflow call, tagged with which workflow ran."""

    def __init__(self, gen_config, prepass_outputs=("/out/intermediate.png",)):
        super().__init__(config=gen_config, ui_callbacks=None)
        self.calls = []
        self._prepass_outputs = list(prepass_outputs)

    def main_workflow(self, **kwargs):
        self.calls.append(("main", kwargs, self.is_producing_intermediate()))
        return ["/out/final.png"]

    def edit_workflow(self, **kwargs):
        self.calls.append(("edit", kwargs, self.is_producing_intermediate()))
        return list(self._prepass_outputs)

    def controlnet_workflow(self, **kwargs):
        self.calls.append(("controlnet", kwargs, self.is_producing_intermediate()))
        return list(self._prepass_outputs)

    def _get_workflows(self):
        return {
            WorkflowType.IP_ADAPTER: self.main_workflow,
            WorkflowType.IMAGE_EDIT: self.edit_workflow,
            WorkflowType.CONTROLNET: self.controlnet_workflow,
        }

    # BaseImageGenerator abstract surface, unused here.
    def prompt_setup(self, *a, **kw):
        raise NotImplementedError

    def simple_image_gen(self, *a, **kw):
        raise NotImplementedError

    def simple_image_gen_lora(self, *a, **kw):
        raise NotImplementedError

    def upscale_simple(self, *a, **kw):
        raise NotImplementedError

    def control_net(self, *a, **kw):
        raise NotImplementedError

    def ip_adapter(self, *a, **kw):
        raise NotImplementedError

    def img2img(self, *a, **kw):
        raise NotImplementedError

    def instant_lora(self, *a, **kw):
        raise NotImplementedError

    def redo_with_different_parameter(self, *a, **kw):
        raise NotImplementedError


def make_generator(prompt=None, **kwargs):
    gen_config = make_gen_config()
    gen_config.prompt_image_path = "/src/original.png"
    gen_config.intermediate_prompt = prompt
    return StubGenerator(gen_config, **kwargs)


def _prompt(**kwargs):
    """The pre-pass as the run carries it: a plain dict, not the UI object."""
    kwargs.setdefault("positive_tags", "black and white")
    return IntermediatePrompt(name="bw", **kwargs).to_dict()


def run(gen, workflow_type=WorkflowType.IP_ADAPTER, **kwargs):
    """Invoke the wrapped callable the way schedule_generation would."""
    task = gen._with_intermediate_pass(workflow_type, gen.main_workflow)
    return task(**kwargs)


def _source():
    adapter = IPAdapter(id="/src/original.png")
    adapter.generation_path = "/src/converted.png"
    return adapter


# ---------------------------------------------------------------------------
# When it does not apply
# ---------------------------------------------------------------------------

class TestWhenItDoesNotApply:
    def test_no_prompt_leaves_the_callable_untouched(self):
        gen = make_generator(prompt=None)
        # Bound to a local: attribute access builds a new bound method each
        # time, so `gen.main_workflow is gen.main_workflow` is False regardless.
        method = gen.main_workflow
        assert gen._with_intermediate_pass(WorkflowType.IP_ADAPTER, method) is method

    def test_a_workflow_with_no_image_leaves_it_untouched(self):
        gen = make_generator(prompt=_prompt())
        method = gen.main_workflow
        assert gen._with_intermediate_pass(WorkflowType.SIMPLE_IMAGE_GEN, method) is method

    def test_a_run_with_no_image_runs_unchanged(self):
        """Nothing to transform, so the run proceeds rather than failing."""
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=None)
        assert [c[0] for c in gen.calls] == ["main"]

    def test_an_unknown_prepass_workflow_runs_unchanged(self):
        gen = make_generator(prompt=_prompt(workflow_type="NOT_A_WORKFLOW"))
        run(gen, ip_adapter=_source())
        assert [c[0] for c in gen.calls] == ["main"]

    def test_an_empty_prompt_leaves_the_callable_untouched(self):
        gen = make_generator(prompt={})
        method = gen.main_workflow
        assert gen._with_intermediate_pass(WorkflowType.IP_ADAPTER, method) is method


# ---------------------------------------------------------------------------
# Order and prompts
# ---------------------------------------------------------------------------

class TestThePassItself:
    def test_the_prepass_runs_before_the_users_workflow(self):
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=_source())
        assert [c[0] for c in gen.calls] == ["edit", "main"]

    def test_the_prepass_uses_its_own_positive_prompt(self):
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=_source(), positive="a house")
        assert gen.calls[0][1]["positive"] == "black and white"

    def test_the_users_positive_prompt_is_untouched(self):
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=_source(), positive="a house")
        assert gen.calls[1][1]["positive"] == "a house"

    def test_the_negative_prompt_is_inherited_by_default(self):
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=_source(), negative="blurry")
        assert gen.calls[0][1]["negative"] == "blurry"

    def test_the_negative_prompt_is_used_when_opted_in(self):
        gen = make_generator(prompt=_prompt(negative_tags="colour", use_negative=True))
        run(gen, ip_adapter=_source(), negative="blurry")
        assert gen.calls[0][1]["negative"] == "colour"

    def test_the_prepass_runs_its_own_workflow(self):
        gen = make_generator(prompt=_prompt(workflow_type=WorkflowType.CONTROLNET))
        run(gen, ip_adapter=_source())
        assert [c[0] for c in gen.calls] == ["controlnet", "main"]


# ---------------------------------------------------------------------------
# Handing the intermediate to the user's workflow
# ---------------------------------------------------------------------------

class TestTheHandover:
    def test_the_user_workflow_reads_the_intermediate(self):
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=_source())
        assert gen.calls[1][1]["ip_adapter"].generation_path == "/out/intermediate.png"

    def test_the_original_still_names_the_lineage(self):
        """id drives EXIF lineage and the edit-suffix rename, so it must stay
        on the user's real source rather than the intermediate."""
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=_source())
        assert gen.calls[1][1]["ip_adapter"].id == "/src/original.png"

    def test_the_source_adapter_is_not_mutated(self):
        """It is shared across run-loop iterations."""
        gen = make_generator(prompt=_prompt())
        source = _source()
        run(gen, ip_adapter=source)
        assert source.generation_path == "/src/converted.png"

    def test_a_prepass_on_another_field_gets_its_own_adapter_type(self):
        gen = make_generator(prompt=_prompt(workflow_type=WorkflowType.CONTROLNET))
        run(gen, ip_adapter=_source())
        prepass_kwargs = gen.calls[0][1]
        assert isinstance(prepass_kwargs["control_net"], ControlNet)
        assert prepass_kwargs["control_net"].generation_path == "/src/converted.png"
        assert "ip_adapter" not in prepass_kwargs

    def test_a_prepass_that_produces_nothing_falls_back_to_the_original(self):
        gen = make_generator(prompt=_prompt(), prepass_outputs=())
        source = _source()
        run(gen, ip_adapter=source)
        assert [c[0] for c in gen.calls] == ["edit", "main"]
        assert gen.calls[1][1]["ip_adapter"] is source


# ---------------------------------------------------------------------------
# The intermediate is not the run's deliverable
# ---------------------------------------------------------------------------

class TestOutputTreatments:
    def test_the_run_output_keeps_its_treatments(self):
        gen = make_generator()
        gen.gen_config.workflow_id = WorkflowType.IMAGE_EDIT
        gen.gen_config.edit_suffix = "_edit"
        gen.gen_config.target_dir = "/somewhere"
        assert gen.output_treatments() == ("_edit", "/somewhere")

    def test_the_intermediate_gets_neither(self):
        """It is kept, but it must not take the deliverable's name or place."""
        gen = make_generator()
        gen.gen_config.workflow_id = WorkflowType.IMAGE_EDIT
        gen.gen_config.edit_suffix = "_edit"
        gen.gen_config.target_dir = "/somewhere"
        gen._intermediate_context.active = True
        assert gen.output_treatments() == ("", None)

    def test_the_mark_is_set_only_during_the_prepass(self):
        gen = make_generator(prompt=_prompt())
        run(gen, ip_adapter=_source())
        marks = {name: mark for name, _kwargs, mark in gen.calls}
        assert marks == {"edit": True, "main": False}

    def test_the_mark_is_cleared_when_the_prepass_raises(self):
        gen = make_generator(prompt=_prompt())
        gen.edit_workflow = lambda **kw: (_ for _ in ()).throw(RuntimeError("backend down"))
        try:
            run(gen, ip_adapter=_source())
        except RuntimeError:
            pass
        assert gen.is_producing_intermediate() is False


# ---------------------------------------------------------------------------
# Pending accounting
# ---------------------------------------------------------------------------

class TestSurvivingSerialization:
    def test_a_restored_run_keeps_its_prepass(self):
        """RunConfig.from_dict rebuilds only the types it knows, so carrying
        the UI object here would lose the pre-pass on a restored run."""
        from sd_runner.run_config import RunConfig

        original = RunConfig()
        original.workflow_tag = WorkflowType.IP_ADAPTER.name
        original.intermediate_prompt = _prompt()

        restored = RunConfig.from_dict(original.to_dict())
        assert restored.intermediate_prompt == original.intermediate_prompt

    def test_the_restored_prepass_still_drives_a_pass(self):
        from sd_runner.run_config import RunConfig

        original = RunConfig()
        original.workflow_tag = WorkflowType.IP_ADAPTER.name
        original.intermediate_prompt = _prompt()

        gen = make_generator(prompt=RunConfig.from_dict(original.to_dict()).intermediate_prompt)
        run(gen, ip_adapter=_source())
        assert [c[0] for c in gen.calls] == ["edit", "main"]


class TestCaching:
    """The point of the feature: a repeated pre-pass is not repeated work."""

    def _existing(self, tmp_path):
        made = tmp_path / "intermediate.png"
        made.write_bytes(b"pixels")
        return str(made)

    def test_a_second_run_reuses_the_first_intermediate(self, app_cache, tmp_path):
        made = self._existing(tmp_path)
        prompt = _prompt()

        first = make_generator(prompt=prompt, prepass_outputs=(made,))
        run(first, ip_adapter=_source())
        second = make_generator(prompt=prompt, prepass_outputs=(made,))
        run(second, ip_adapter=_source())

        assert [c[0] for c in first.calls] == ["edit", "main"]
        assert [c[0] for c in second.calls] == ["main"]

    def test_the_reused_intermediate_still_reaches_the_workflow(self, app_cache, tmp_path):
        made = self._existing(tmp_path)
        prompt = _prompt()

        run(make_generator(prompt=prompt, prepass_outputs=(made,)), ip_adapter=_source())
        second = make_generator(prompt=prompt, prepass_outputs=(made,))
        run(second, ip_adapter=_source())

        assert second.calls[0][1]["ip_adapter"].generation_path == made
        assert second.calls[0][1]["ip_adapter"].id == "/src/original.png"

    def test_a_different_prompt_generates_its_own(self, app_cache, tmp_path):
        made = self._existing(tmp_path)
        run(make_generator(prompt=_prompt(), prepass_outputs=(made,)), ip_adapter=_source())

        other = make_generator(
            prompt=_prompt(positive_tags="a drawing"), prepass_outputs=(made,)
        )
        run(other, ip_adapter=_source())
        assert [c[0] for c in other.calls] == ["edit", "main"]

    def test_a_vanished_intermediate_is_regenerated(self, app_cache, tmp_path):
        made = self._existing(tmp_path)
        prompt = _prompt()
        run(make_generator(prompt=prompt, prepass_outputs=(made,)), ip_adapter=_source())

        import os
        os.remove(made)
        second = make_generator(prompt=prompt, prepass_outputs=(made,))
        run(second, ip_adapter=_source())
        assert [c[0] for c in second.calls] == ["edit", "main"]

    def test_more_variants_means_more_generations_before_reuse(self, app_cache, tmp_path):
        prompt = _prompt(max_variants=2)
        first_path = tmp_path / "one.png"
        second_path = tmp_path / "two.png"
        for path in (first_path, second_path):
            path.write_bytes(b"pixels")
        first_path, second_path = str(first_path), str(second_path)

        first = make_generator(prompt=prompt, prepass_outputs=(first_path,))
        run(first, ip_adapter=_source())
        second = make_generator(prompt=prompt, prepass_outputs=(second_path,))
        run(second, ip_adapter=_source())
        third = make_generator(prompt=prompt, prepass_outputs=(second_path,))
        run(third, ip_adapter=_source())

        assert [c[0] for c in second.calls] == ["edit", "main"]
        assert [c[0] for c in third.calls] == ["main"]


class TestPendingCount:
    def test_the_prepass_counts_while_it_runs(self):
        gen = make_generator(prompt=_prompt())
        seen = []
        underlying = gen.edit_workflow

        def recording(**kwargs):
            seen.append(gen.pending_counter)
            return underlying(**kwargs)

        gen.edit_workflow = recording
        before = gen.pending_counter
        run(gen, ip_adapter=_source())
        assert seen == [before + 1]

    def test_the_prepass_releases_its_count(self):
        gen = make_generator(prompt=_prompt())
        before = gen.pending_counter
        run(gen, ip_adapter=_source())
        assert gen.pending_counter == before

    def test_a_prepass_that_raises_still_releases_its_count(self):
        gen = make_generator(prompt=_prompt())
        gen.edit_workflow = lambda **kw: (_ for _ in ()).throw(RuntimeError("backend down"))
        before = gen.pending_counter
        try:
            run(gen, ip_adapter=_source())
        except RuntimeError:
            pass
        assert gen.pending_counter == before
