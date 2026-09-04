"""Object factories shared across the test suite.

Each factory exists because constructing the real object directly drags in a
dependency a test does not want:

- ``make_model`` passes an explicit ``path`` so ``Model`` never falls back to
  ``Model.MODELS_DIR`` (bound from config at class-definition time).
- ``make_prompter_config`` zeroes the stop/return insertion chances, which are
  0.5 by default and would otherwise rewrite punctuation at random.
- ``make_gen_config`` supplies fresh adapter/vae/lora lists, because
  ``GenConfig`` declares those as mutable default arguments and ``prepare()``
  appends a ``None`` sentinel to whichever list it is handed -- configs built
  without them would share one list and accumulate sentinels across tests.
- ``FakeServerConn`` stands in for an accepted socket, so ``SDRunnerServer``'s
  receive loop can be driven without binding a port.
"""

from sd_runner.gen_config import GenConfig
from sd_runner.models import Model
from sd_runner.prompter import Prompter
from sd_runner.prompter_configuration import PrompterConfiguration
from sd_runner.resolution import Resolution
from sd_runner.run_config import RunConfig
from sd_runner.schedule import PresetTask, Schedule
from utils.globals import PromptMode


def make_model(id="model.safetensors", path="some/path", **kwargs) -> Model:
    """Construct a Model with an explicit path to avoid a MODELS_DIR dependency."""
    return Model(id=id, path=path, **kwargs)


def make_resolution(width=1024, height=1024, **kwargs) -> Resolution:
    return Resolution(width=width, height=height, **kwargs)


def make_run_config(**kwargs) -> RunConfig:
    """A RunConfig from a plain dict of args (``None`` when no args given)."""
    return RunConfig(args=kwargs if kwargs else None)


class FakeServerConn:
    """An accepted connection that replays scripted messages, then hangs up.

    Assign to ``SDRunnerServer._conn`` and call ``_handle_connection()`` to
    exercise the receive loop -- message parsing, client-id adoption, dispatch
    -- without a listener or a port. ``recv`` raises ``EOFError`` once the
    script is exhausted, which is how a real client disconnecting looks, so the
    loop exits on its own. Replies land in ``sent``.
    """

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    def recv(self):
        if not self._messages:
            raise EOFError
        return self._messages.pop(0)

    def send(self, msg):
        self.sent.append(msg)

    def close(self):
        pass


def make_prompter_config(
    prompt_mode: PromptMode = PromptMode.FIXED,
    *,
    categories: dict = None,
    **overrides,
) -> PrompterConfiguration:
    """A PrompterConfiguration with the random punctuation passes disabled.

    *categories* maps a category name to a ConceptConfiguration, for tests that
    need a range the shipped defaults do not provide (``nonsense`` defaults to
    ``(0, 0)``, for instance). Any other keyword is set as a plain attribute.
    """
    config = PrompterConfiguration()
    config.prompt_mode = prompt_mode
    config.stop_insertion_chance = 0.0
    config.return_insertion_chance = 0.0
    for name, concept_config in (categories or {}).items():
        config.set_category_config(name, concept_config)
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def make_prompter(
    prompt_mode: PromptMode = PromptMode.FIXED,
    *,
    prompt_list: list = None,
    categories: dict = None,
    **config_overrides,
) -> Prompter:
    """A Prompter over a make_prompter_config().

    Prompter's class-level tag state (POSITIVE_TAGS and friends) is reset
    between tests by the root conftest, so callers do not need to manage it.
    """
    config = make_prompter_config(prompt_mode, categories=categories, **config_overrides)
    kwargs = {"prompter_config": config}
    if prompt_list is not None:
        kwargs["prompt_list"] = prompt_list
    return Prompter(**kwargs)


def make_schedule(name="Test Schedule", tasks=()):
    """A preset Schedule, optionally populated from (preset_name, count_runs) pairs.

    This covers preset schedules only. TimedSchedule has its own factories in
    test_timed_schedule.py and test_timed_schedules_manager.py; they are kept
    separate because they disagree on the default weekday_options (Mon-Fri
    versus all seven), and that default is load-bearing for those tests.
    """
    schedule = Schedule()
    schedule.name = name
    for task_name, count_runs in (tasks or ()):
        schedule.add_preset_task(PresetTask(task_name, count_runs))
    return schedule


def make_app_actions():
    """An AppActions with a no-op callback bound to every required action."""
    from sd_runner.ui.app_actions import AppActions

    def noop(*args, **kwargs):
        return None

    return AppActions({action: noop for action in AppActions.REQUIRED_ACTIONS})


def make_gen_config(**kwargs) -> GenConfig:
    """A minimal valid GenConfig; any field can be overridden by keyword."""
    defaults = dict(
        workflow_id="simple_image_gen.json",
        n_latents=1,
        positive="a sunset",
        negative="blurry",
        models=[make_model()],
        vaes=[],
        control_nets=[],
        ip_adapters=[],
        loras=[],
        resolutions=[make_resolution()],
        run_config=make_run_config(seed=42),
    )
    defaults.update(kwargs)
    return GenConfig(**defaults)
