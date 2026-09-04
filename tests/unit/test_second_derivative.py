"""Second derivatives — feeding each generated image back through its workflow.

The flag re-runs the *same* workflow with the *same* settings, changing only the
input image. So most of what is worth asserting is what does **not** change
between the two passes.

``BaseImageGenerator`` is abstract and its concrete subclasses talk to a
backend, so these drive a minimal stub subclass: the workflow method records
the adapter it was handed and reports output paths, and nothing touches a
network.
"""

import pytest

from sd_runner.generators.base import BaseImageGenerator, logger as base_logger
from sd_runner.models.model_adapters import ControlNet, IPAdapter
from tests.utils import captured_logs, make_gen_config
from utils.globals import (
    CONTROL_NET_IMAGE_WORKFLOWS,
    IP_ADAPTER_IMAGE_WORKFLOWS,
    WorkflowType,
    image_input_field,
)


class StubGenerator(BaseImageGenerator):
    """Records each workflow call and reports the paths it 'produced'."""

    def __init__(self, gen_config, outputs_per_call=("/out/a.png",)):
        super().__init__(config=gen_config, ui_callbacks=None)
        self.calls = []
        self._outputs = list(outputs_per_call)
        self._call_count = 0

    def workflow(self, **kwargs):
        self.calls.append(kwargs)
        self._call_count += 1
        # Only the first pass produces new files in these tests; a derivative
        # reporting more paths would recurse, which the design does not do.
        return list(self._outputs) if self._call_count == 1 else []

    # BaseImageGenerator abstract surface, unused here.
    def _get_workflows(self):
        return {}

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


def make_generator(second_derivative=True, outputs=("/out/a.png",)):
    gen_config = make_gen_config()
    gen_config.second_derivative = second_derivative
    gen_config.prompt_image_path = "/src/original.png"
    return StubGenerator(gen_config, outputs_per_call=outputs)


def run(gen, workflow_type, **kwargs):
    """Invoke the wrapped callable the way schedule_generation would."""
    task = gen._with_second_derivative(workflow_type, gen.workflow)
    return task(**kwargs)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------

class TestWhichWorkflowsQualify:
    @pytest.mark.parametrize("workflow_type", CONTROL_NET_IMAGE_WORKFLOWS)
    def test_control_net_workflows_use_the_control_net_field(self, workflow_type):
        assert image_input_field(workflow_type) == "control_net"

    @pytest.mark.parametrize("workflow_type", IP_ADAPTER_IMAGE_WORKFLOWS)
    def test_ip_adapter_workflows_use_the_ip_adapter_field(self, workflow_type):
        assert image_input_field(workflow_type) == "ip_adapter"

    @pytest.mark.parametrize("workflow_type", [
        WorkflowType.SIMPLE_IMAGE_GEN,
        WorkflowType.SIMPLE_IMAGE_GEN_LORA,
        WorkflowType.TURBO,
    ])
    def test_a_workflow_with_no_image_input_has_no_field(self, workflow_type):
        assert image_input_field(workflow_type) is None

    @pytest.mark.parametrize("workflow_type, field", [
        (WorkflowType.INSTANT_LORA, "ip_adapter"),
        (WorkflowType.INPAINT_CLIPSEG, "control_net"),
        (WorkflowType.UPSCALE_SIMPLE, "control_net"),
        (WorkflowType.UPSCALE_BETTER, "control_net"),
    ])
    def test_workflows_that_rename_their_image_still_declare_it(
        self, workflow_type, field
    ):
        """These read an image but hand it to a differently-named node input.

        They were absent from both tuples, so image-dependent features saw
        None and silently skipped them.
        """
        assert image_input_field(workflow_type) == field

    def test_instant_lora_offers_its_content_image_not_its_structural_one(self):
        """It reads both adapters; only the ip_adapter one is substitutable."""
        assert image_input_field(WorkflowType.INSTANT_LORA) == "ip_adapter"

    def test_animate_diff_declares_no_single_input_image(self):
        """Deliberate, not an omission.

        Its two adapters are the ends of an interpolation rather than one
        image to swap, and it emits a frame per generation -- so re-running it
        once per output image would multiply an animation by its frame count.
        """
        assert image_input_field(WorkflowType.ANIMATE_DIFF) is None

    def test_a_workflow_with_no_image_input_is_left_alone(self):
        """The checkbox is run-level; switching workflow must not break a run."""
        gen = make_generator(second_derivative=True)
        # Bound once: gen.workflow builds a new bound method on every access, so
        # comparing two separate lookups would fail even when nothing wrapped it.
        workflow = gen.workflow
        assert gen._with_second_derivative(
            WorkflowType.SIMPLE_IMAGE_GEN, workflow
        ) is workflow

    def test_the_flag_off_leaves_the_callable_untouched(self):
        gen = make_generator(second_derivative=False)
        workflow = gen.workflow
        assert gen._with_second_derivative(
            WorkflowType.IP_ADAPTER, workflow
        ) is workflow

    def test_the_flag_off_runs_the_workflow_once(self):
        gen = make_generator(second_derivative=False)
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert len(gen.calls) == 1


# ---------------------------------------------------------------------------
# The derivative pass
# ---------------------------------------------------------------------------

class TestTheDerivativeRuns:
    def test_one_image_becomes_two_generations(self):
        gen = make_generator()
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert len(gen.calls) == 2

    def test_the_second_pass_takes_the_first_pass_output_as_its_input(self):
        gen = make_generator(outputs=("/out/a.png",))
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert gen.calls[1]["ip_adapter"].generation_path == "/out/a.png"

    def test_a_control_net_workflow_swaps_the_control_net_instead(self):
        gen = make_generator()
        run(gen, WorkflowType.CONTROLNET, control_net=ControlNet(id="/src/original.png"))
        assert gen.calls[1]["control_net"].generation_path == "/out/a.png"

    def test_every_output_gets_its_own_derivative(self):
        """One-for-one: n_latents > 1 means one derivative per image."""
        gen = make_generator(outputs=("/out/a.png", "/out/b.png", "/out/c.png"))
        run(gen, WorkflowType.IMG2IMG, ip_adapter=IPAdapter(id="/src/original.png"))
        assert len(gen.calls) == 4
        assert [c["ip_adapter"].generation_path for c in gen.calls[1:]] == [
            "/out/a.png", "/out/b.png", "/out/c.png"
        ]

    def test_the_derivative_does_not_derive_again(self):
        """Depth two. A derivative reporting no paths must not recurse."""
        gen = make_generator()
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert len(gen.calls) == 2

    def test_the_wrapper_still_reports_the_first_pass_paths(self):
        gen = make_generator(outputs=("/out/a.png",))
        assert run(
            gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png")
        ) == ["/out/a.png"]


# ---------------------------------------------------------------------------
# Everything except the image is inherited
# ---------------------------------------------------------------------------

class TestOnlyTheImageChanges:
    def test_adapter_strength_is_carried_over(self):
        """The point of the feature: same settings, one link along."""
        gen = make_generator()
        run(gen, WorkflowType.IP_ADAPTER,
            ip_adapter=IPAdapter(id="/src/original.png", strength=0.42))
        assert gen.calls[1]["ip_adapter"].strength == 0.42

    def test_every_other_argument_is_passed_through_unchanged(self):
        gen = make_generator()
        run(gen, WorkflowType.IP_ADAPTER,
            ip_adapter=IPAdapter(id="/src/original.png"),
            model="a_model", lora="a_lora", positive="a prompt", n_latents=3)
        first, second = gen.calls
        for key in ("model", "lora", "positive", "n_latents"):
            assert second[key] == first[key]

    def test_the_original_adapter_is_not_mutated(self):
        """It is shared across iterations of the run loop."""
        adapter = IPAdapter(id="/src/original.png")
        original_path = adapter.generation_path
        gen = make_generator()
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=adapter)
        assert adapter.generation_path == original_path

    def test_the_first_pass_kwargs_are_not_mutated(self):
        gen = make_generator()
        adapter = IPAdapter(id="/src/original.png")
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=adapter)
        assert gen.calls[0]["ip_adapter"] is adapter


# ---------------------------------------------------------------------------
# Lineage and bookkeeping
# ---------------------------------------------------------------------------

class TestLineageAndCounters:
    def test_the_run_source_is_the_related_image_outside_a_derivative(self):
        gen = make_generator()
        assert gen.related_image_path() == "/src/original.png"

    def test_the_derivative_records_its_own_parent(self):
        """Not the start of the chain -- the image it was actually made from."""
        seen = []
        gen = make_generator()
        original_workflow = gen.workflow

        def recording(**kwargs):
            seen.append(gen.related_image_path())
            return original_workflow(**kwargs)

        task = gen._with_second_derivative(WorkflowType.IP_ADAPTER, recording)
        task(ip_adapter=IPAdapter(id="/src/original.png"))
        assert seen == ["/src/original.png", "/out/a.png"]

    def test_the_override_is_cleared_after_the_derivative(self):
        """The thread is returned to the pool and will run unrelated work."""
        gen = make_generator()
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert gen.related_image_path() == "/src/original.png"

    def test_the_derivative_counts_itself_while_it_runs(self):
        """A derived pass is a generation in flight and is counted as one."""
        gen = make_generator()
        before = gen.pending_counter
        seen = []
        underlying = gen.workflow

        def recording_workflow(**kwargs):
            seen.append(gen.pending_counter)
            return underlying(**kwargs)

        gen.workflow = recording_workflow
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))

        # The parent pass here is called directly rather than through
        # _wrap_task, so only the derived pass is counted.
        assert seen == [before, before + 1]

    def test_the_derivative_releases_its_count_when_it_finishes(self):
        """The pass owns the count it took, so nothing is left in flight."""
        gen = make_generator()
        before = gen.pending_counter
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert gen.pending_counter == before

    def test_a_derivative_that_raises_still_releases_its_count(self):
        """The leak this accounting exists to prevent."""
        gen = make_generator()
        before = gen.pending_counter
        calls = []

        def failing_on_the_derived_pass(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return ["/out/a.png"]
            raise RuntimeError("backend never reached")

        gen.workflow = failing_on_the_derived_pass
        with pytest.raises(RuntimeError):
            run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert gen.pending_counter == before

    def test_a_pass_and_its_derivative_each_release_their_own_count(self):
        """Both arms are outstanding at once, so neither may displace the other.

        The stub reaches no backend, so nothing releases early: the parent's
        arm is still owed when the derivative arms on the same thread, and only
        the task wrapper is left to settle it.
        """
        gen = make_generator()
        before = gen.pending_counter
        task = gen._wrap_task(
            gen._with_second_derivative(WorkflowType.IP_ADAPTER, gen.workflow)
        )

        gen.count_pending_dispatch()  # what schedule_generation would have taken
        task(ip_adapter=IPAdapter(id="/src/original.png"))

        assert gen.pending_counter == before


# ---------------------------------------------------------------------------
# Nothing to derive from
# ---------------------------------------------------------------------------

class TestNoOutputPath:
    def test_no_output_path_does_not_raise(self):
        """The parent image may still exist; the run carries on regardless."""
        gen = make_generator(outputs=())
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert len(gen.calls) == 1

    def test_no_output_path_is_logged_as_an_error(self, caplog):
        gen = make_generator(outputs=())
        with captured_logs(caplog, base_logger):
            run(gen, WorkflowType.IP_ADAPTER, ip_adapter=IPAdapter(id="/src/original.png"))
        assert "Second derivative skipped" in caplog.text

    def test_a_missing_adapter_is_logged_and_skipped(self):
        """An eligible workflow with nothing in its image field."""
        gen = make_generator()
        run(gen, WorkflowType.IP_ADAPTER, ip_adapter=None)
        assert len(gen.calls) == 1
