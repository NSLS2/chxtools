
"""
RunEngine metadata normalizer for registering, validating, and injecting workflows.

Provides ``WorkflowManager`` for managing per-run workflow configurations across
``once``, ``greedy``, ``strict``, and shared ``common`` slots, resolving shared models
and workflow dependencies before attaching serialized payloads to ``md["workflows"]``.
"""

from collections.abc import Callable, Mapping
from typing import Any, TypeAlias

from pydantic import BaseModel

from .projection import MDProjector
from .workflow import Workflow

WorkflowKey: TypeAlias = Workflow | type[BaseModel] | str


class _WorkflowSlot(dict[str, BaseModel]):
    """Multi-modal dictionary normalizing workflow/model keys to names and validating payloads."""

    def __init__(self, registry: dict[str, Any]) -> None:
        super().__init__()
        self._registry = registry

    def _key(self, key: WorkflowKey) -> str:
        if isinstance(key, str):
            return key
        self._registry[key.__name__] = key
        return key.__name__

    def __getitem__(self, key: WorkflowKey) -> BaseModel:
        return super().__getitem__(self._key(key))

    def __setitem__(self, key: Workflow | type[BaseModel], value: Any) -> None:  # type: ignore[override]
        if isinstance(key, str):
            raise KeyError("for validation purposes workflow registration using bare strings is prohibited")
        name = self._key(key)
        schema = key.schema if isinstance(key, Workflow) else key
        match value:
            case None | False:
                self.pop(name, None)
            case BaseModel():
                super().__setitem__(name, value)
            case True:
                super().__setitem__(name, schema())
            case _:
                super().__setitem__(name, schema.model_validate(value))

    def __delitem__(self, key: WorkflowKey) -> None:
        super().__delitem__(self._key(key))

    def __contains__(self, key: object) -> bool:
        return super().__contains__(key if isinstance(key, str) else getattr(key, "__name__", key))


class WorkflowManager:
    """
    Workflow Manager system used as a convenience to 'automagically' add validated workflows to each run.

    ...without having to do it every call.

    technical:
    is intended to be used in the md_normalizer slot of the RunEngine where it'll add workflows to the 'workflows'
    md element

    it has 4 different types of workflow slots:
        workflows:
            once:
                added to the next run plan if the workflow schema is fulfilled, then discarded
            greedy:
                added to all plans as long as the schema has been fulfilled, does nothing if not fulfilled
            strict:
                used like greedy but either errors or forces input if schema is not fulfilled so that values that are
                truly expected to change per run are enforced

    expected runtime syntax:
    wf_manager = WorkflowManager()
    RE = RunEngine(..., md_normalizer=wf_manager)

    tpx_convert = gen_images_for_run.schema(dt=1)

    wf_manager.greedy[gen_images_for_run] = tpx_convert  # or True / {} if all fields have defaults

    RE(some_plan())

    wf_manager.greedy[gen_images_for_run] = None
    """

    def __init__(
        self,
        projector: Callable[[Mapping[str, Any]], Mapping[str, BaseModel | None]] | None = None,
        force_input: bool = False,
    ) -> None:
        self._registry: dict[str, Workflow] = {}
        self._common_registry: dict[str, type[BaseModel]] = {}
        self.once = _WorkflowSlot(self._registry)
        self.greedy = _WorkflowSlot(self._registry)
        self.strict = _WorkflowSlot(self._registry)
        self.common = _WorkflowSlot(self._common_registry)
        self.force_input = force_input
        # projector takes raw run md and synthesizes shared models for the common slot
        self.projector = projector if projector is not None else MDProjector()

    def _prompt_model(self, model_cls: type[BaseModel]) -> BaseModel:
        return model_cls.model_validate(
            {
                name: input(f"[{model_cls.__name__}] please input value for field {name}: ")
                for name, field in model_cls.model_fields.items()
                if field.is_required()
            }
        )

    def __call__(self, md: dict[str, Any]) -> dict[str, Any]:
        workflows: dict[str, Any] = {}
        common = self.common | dict(self.projector(md))
        required = self.strict | self.once
        candidates = self.greedy | required
        self.once.clear()

        for name, val in candidates.items():
            wf = self._registry[name]
            is_req = name in required
            if missing_common := {c for c in wf.common if c.__name__ not in common}:
                if not is_req:
                    print(f"workflow [{name}] skipped due to missing common element(s):\n",
                          *(f"\t{e.__name__ }" for e in missing_common))
                    continue
                if not self.force_input:
                    raise RuntimeError(
                        f"values could not be synthesized for workflow '{name}' "
                        "issue: missing common dataclass"
                    )
                for cls in missing_common:
                    common[cls.__name__] = self._prompt_model(cls)

            workflows[name] = val.model_dump()

        while invalid := {
            name for name in workflows if not ({d.__name__ for d in self._registry[name].depends} <= workflows.keys())
        }:
            if failed := invalid & required.keys():
                raise RuntimeError(f"values could not be synthesized for workflow(s): {', '.join(failed)}")
            for name in invalid:
                del workflows[name]

        workflows["common"] = {k: (v.model_dump() if v else None) for k, v in common.items()}
        return md | {"workflows": workflows}
