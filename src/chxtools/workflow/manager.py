
"""
RunEngine metadata normalizer for registering, validating, and injecting workflows.

Provides ``WorkflowManager`` for managing per-run workflow configurations across
``once``, ``greedy``, ``strict``, and shared ``common`` slots, resolving shared models
and workflow dependencies before attaching serialized payloads to ``md["workflows"]``.
"""

from collections.abc import Callable, Iterator, Mapping, MutableMapping
from typing import Any

from pydantic import BaseModel

from .workflow import Workflow


class _WorkflowSlot(MutableMapping[Workflow | type[BaseModel] | str, Any]):
    """Mutable mapping that normalizes keys to names and validates payloads on assignment."""

    def __init__(
        self,
        store: dict[str, BaseModel],
        registry: dict[str, Any],
    ) -> None:
        self._store = store
        self._registry = registry

    def _key(self, key: Workflow | type[BaseModel] | str) -> str:
        if isinstance(key, str):
            return key
        self._registry[key.__name__] = key
        return key.__name__

    def __getitem__(self, key: Workflow | type[BaseModel] | str) -> BaseModel:
        return self._store[self._key(key)]

    def __setitem__(self, key: Workflow | type[BaseModel] | str, value: Any) -> None:
        name = self._key(key)
        target = self._registry[name]
        schema = target.schema if isinstance(target, Workflow) else target
        match value:
            case None | False:
                self._store.pop(name, None)
            case BaseModel():
                self._store[name] = value
            case True:
                self._store[name] = schema()
            case _:
                self._store[name] = schema.model_validate(value)

    def __delitem__(self, key: Workflow | type[BaseModel] | str) -> None:
        del self._store[self._key(key)]

    def __iter__(self) -> Iterator[str]:
        return iter(self._store)

    def __len__(self) -> int:
        return len(self._store)

    def __repr__(self) -> str:
        return repr(self._store)


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
        projector: Callable[[dict[str, Any]], Mapping[Workflow | type[BaseModel] | str, Any]] = lambda _: {},
        force_input: bool = False,
    ) -> None:
        self._once: dict[str, BaseModel] = {}
        self._greedy: dict[str, BaseModel] = {}
        self._strict: dict[str, BaseModel] = {}
        self._common: dict[str, BaseModel] = {}
        self._registry: dict[str, Workflow] = {}
        self._common_registry: dict[str, type[BaseModel]] = {}
        self.force_input = force_input
        # projector is a special type of convenience function that takes what is passed in md
        # and makes a default model/dataclass to put in common for better structured data
        # returns a dict of dataclasses
        self._projector = projector

    @property
    def once(self) -> _WorkflowSlot:
        return _WorkflowSlot(self._once, self._registry)

    @property
    def greedy(self) -> _WorkflowSlot:
        return _WorkflowSlot(self._greedy, self._registry)

    @property
    def strict(self) -> _WorkflowSlot:
        return _WorkflowSlot(self._strict, self._registry)

    @property
    def common(self) -> _WorkflowSlot:
        return _WorkflowSlot(self._common, self._common_registry)

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
        self.common.update(self._projector(md))
        required = self._strict | self._once
        candidates = self._greedy | required
        self._once.clear()

        for name, val in candidates.items():
            wf = self._registry[name]
            is_req = name in required
            if missing_common := {c for c in wf.common if c.__name__ not in self._common}:
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
                    self.common[cls] = self._prompt_model(cls)

            workflows[name] = val.model_dump()

        while invalid := {
            name for name in workflows if not ({d.__name__ for d in self._registry[name].depends} <= workflows.keys())
        }:
            if failed := invalid & required.keys():
                raise RuntimeError(f"values could not be synthesized for workflow(s): {', '.join(failed)}")
            for name in invalid:
                del workflows[name]

        workflows["common"] = {k: v.model_dump() for k, v in self._common.items()}
        return md | {"workflows": workflows}
