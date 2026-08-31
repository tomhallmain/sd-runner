"""A SD Web UI response that carries no images.

That is a generation which completed and wrote nothing, not a crash -- the
same contract ComfyGen's queue_prompt follows. It used to be both: an absent
``images`` key raised TypeError out of ``enumerate(None)`` and an empty list
left ``save_path`` unbound at the return. Either landed before the pending
count was released, so the failure also leaked a generation from the count.
"""

import json

import pytest

from sd_runner.generators.sdwebui import SDWebuiGen
from tests.utils import make_gen_config


class StubResponse:
    """Only ``read`` is used, and only once."""

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


@pytest.fixture
def gen():
    generator = SDWebuiGen(make_gen_config(), ui_callbacks=None)
    # save_image_data releases the pending count; arm it so the release is
    # real, as it would be inside a scheduled task.
    generator.count_pending_dispatch()
    generator._arm_pending_release()
    return generator


class TestNoImagesInResponse:
    @pytest.mark.parametrize("payload", [
        pytest.param({"images": []}, id="empty-list"),
        pytest.param({}, id="key-absent"),
        pytest.param({"images": None}, id="key-null"),
    ])
    def test_it_returns_no_path_rather_than_raising(self, gen, payload):
        assert gen.save_image_data(StubResponse(payload)) is None

    @pytest.mark.parametrize("payload", [
        pytest.param({"images": []}, id="empty-list"),
        pytest.param({}, id="key-absent"),
        pytest.param({"images": None}, id="key-null"),
    ])
    def test_the_pending_count_is_still_released(self, gen, payload):
        before = gen.pending_counter
        gen.save_image_data(StubResponse(payload))
        assert gen.pending_counter == before - 1
