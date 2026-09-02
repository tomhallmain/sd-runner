"""IntermediatePrompt -- a pre-pass generation over the reference image.

Prompt text and a workflow. Everything else the pass needs -- model,
resolution, strength, prompt mode, edit suffix -- is inherited from the main
configuration, so the pass is the user's own run with different words and a
possibly different workflow, rather than a second configuration to keep in
step.

The workflow is carried because the transformation need not be the same kind of
operation as the user's own run. It is restricted to workflows that take an
input image, since the pass has nothing to transform otherwise.

The negative prompt is opt-in: unchecked, the pass inherits the main
configuration's negative prompt.
"""

from utils.globals import WorkflowType, image_input_field


class IntermediatePrompt:
    #: Transforming the reference image is the whole point, so a workflow that
    #: takes no input image cannot serve as a pre-pass.
    @staticmethod
    def eligible_workflows() -> list:
        return [wf for wf in WorkflowType if image_input_field(wf) is not None]

    DEFAULT_WORKFLOW = WorkflowType.IMAGE_EDIT

    def __init__(
        self,
        name: str,
        positive_tags: str = "",
        negative_tags: str = "",
        use_negative: bool = False,
        workflow_type=None,
    ) -> None:
        self.name = name
        self.positive_tags = positive_tags
        self.negative_tags = negative_tags
        self.use_negative = use_negative
        if workflow_type is None:
            workflow_type = IntermediatePrompt.DEFAULT_WORKFLOW
        self.workflow_type = (
            workflow_type.name if isinstance(workflow_type, WorkflowType) else workflow_type
        )

    def is_valid(self) -> bool:
        return bool(self.name) and bool(self.positive_tags.strip())

    def readable_str(self) -> str:
        return f"{self.name} ({self.workflow_type}): {self.positive_tags}"

    def __str__(self) -> str:
        return self.readable_str()

    def __eq__(self, other) -> bool:
        if not isinstance(other, IntermediatePrompt):
            return False
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "positive_tags": self.positive_tags,
            "negative_tags": self.negative_tags,
            "use_negative": self.use_negative,
            "workflow_type": self.workflow_type,
        }

    @classmethod
    def from_dict(cls, dict_data: dict) -> "IntermediatePrompt":
        return cls(
            name=dict_data.get("name", ""),
            positive_tags=dict_data.get("positive_tags", ""),
            negative_tags=dict_data.get("negative_tags", ""),
            use_negative=bool(dict_data.get("use_negative", False)),
            workflow_type=dict_data.get("workflow_type"),
        )
