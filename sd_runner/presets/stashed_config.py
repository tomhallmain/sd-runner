"""StashedConfig -- a named run configuration, recalled by name rather than index.

The complement to ``Preset``. A preset carries the four prompt fields; a stash
carries everything else about a run, so the two sit side by side in
``PresetsWindow`` without overlapping.
"""

import datetime


class StashedConfig:
    """A named snapshot of a ``RunnerAppConfig``.

    The complete config dict is kept rather than a filtered subset, because
    ``RunnerAppConfig.from_dict`` replaces the instance dict outright and
    backfills only some of the fields it drops -- ``positive_tags``,
    ``negative_tags`` and ``prompter_config`` are not among them, so a dict
    saved without them raises on the first read.

    The prompt text is emptied rather than omitted: the keys survive for
    ``from_dict``, and no stash retains prompt text that the blacklist purge
    would have stripped from run history.
    """

    def __init__(self, name: str, config: dict, saved_at: str = None) -> None:
        self.name = name
        self.config = config
        self.saved_at = saved_at or datetime.datetime.now().isoformat()

    def is_valid(self) -> bool:
        return bool(self.name) and isinstance(self.config, dict) and bool(self.config)

    def readable_str(self) -> str:
        workflow = str(self.config.get("workflow_type", ""))
        models = str(self.config.get("model_tags", ""))
        detail = ", ".join(part for part in (workflow, models) if part)
        return f"{self.name} ({detail})" if detail else self.name

    def __str__(self) -> str:
        return self.readable_str()

    def __eq__(self, other) -> bool:
        if not isinstance(other, StashedConfig):
            return False
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "config": self.config,
            "saved_at": self.saved_at,
        }

    @classmethod
    def from_dict(cls, dict_data: dict) -> "StashedConfig":
        return cls(
            name=dict_data.get("name", ""),
            config=dict_data.get("config", {}),
            saved_at=dict_data.get("saved_at"),
        )

    @staticmethod
    def from_runner_app_config(name, runner_app_config) -> "StashedConfig":
        """Snapshot *runner_app_config*, with the prompt text left out."""
        config = runner_app_config.to_dict()
        config["positive_tags"] = ""
        config["negative_tags"] = ""
        return StashedConfig(name, config)
