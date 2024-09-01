

class Preset:
    def __init__(self, workflow_type, positive_tags, negative_tags) -> None:
        self.workflow_type = workflow_type
        self.positive_tags = positive_tags
        self.negative_tags = negative_tags

    def is_valid(self):
        return True

    def readable_str(self):
        positive = self.positive_tags.replace("\n", "")[0:40]
        return f"{self.workflow_type} {positive}"

    def __str__(self):
        return self.readable_str()

    def __eq__(self, other):
        if not isinstance(other, Preset):
            return False
        return self.workflow_type == other.workflow_type \
            and self.positive_tags == other.positive_tags \
            and self.negative_tags == other.negative_tags

    def __hash__(self):
        return hash((self.workflow_type, self.positive_tags, self.negative_tags))

    def to_dict(self):
        return {
            'workflow_type': self.workflow_type,
            'positive_tags': self.positive_tags,
            'negative_tags': self.negative_tags
            }
    
    @classmethod
    def from_dict(cls, dict_data: dict) -> 'Preset':
        return cls(**dict_data)

    @staticmethod
    def from_runner_app_config(runner_app_config) -> 'Preset':
        return Preset(runner_app_config.workflow_type, runner_app_config.positive_tags, runner_app_config.negative_tags)