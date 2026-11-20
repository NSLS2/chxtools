"""
Metadata projection utilities for synthesizing shared workflow models from raw run metadata.

``MDProjector`` bridges flat Bluesky start-document metadata (such as ``detectors`` or
legacy ``auto_pipeline`` keys) into validated Pydantic models placed in the
``WorkflowManager`` ``common`` slot.

Example
-------
>>> def confirm_det_setup(md: Mapping[str, Any]) -> BaseModel | None:
...     if "eiger4m_single" in md.get("detectors", []):
...         return DetConfig(...)
...     return None
...
>>> projector = MDProjector(BlueskyRun)
>>> projector.triggers["detectors"] = confirm_det_setup
>>> projected_common = projector(raw_md)
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel

from ..protocols import BlueskyRun

ProjectedModels: TypeAlias = (
    BaseModel
    | list[BaseModel]
    | tuple[BaseModel, ...]
    | set[BaseModel]
    | Mapping[str, BaseModel | None]
    | None
)
TriggerFn: TypeAlias = Callable[[Mapping[str, Any]], ProjectedModels]


class _TriggerMap(dict[str, TriggerFn]):
    """Dictionary mapping valid run-schema field names to metadata projection callbacks."""

    def __init__(self, allowed_fields: Iterable[str]) -> None:
        super().__init__()
        self._allowed_fields = set(allowed_fields)

    def __setitem__(self, field: str, callback: TriggerFn | Literal[False] | None) -> None:  # type: ignore[override]
        if field not in self._allowed_fields:
            raise KeyError(f"Run schema does not contain field {field!r}")
        if callback:
            super().__setitem__(field, callback)
        else:
            self.pop(field, None)


class MDProjector:
    """
    Callable metadata projector that runs field-keyed triggers against raw run metadata.

    When called with a run metadata mapping ``md``, every trigger whose field name is
    present in ``md`` is invoked with ``md`` and its returned Pydantic model(s) are
    merged into a ``{model_class_name: model_instance}`` dictionary suitable for
    ``WorkflowManager.common``. Returning ``{model_class_name: None}`` via a mapping
    indicates that the required fields already reside directly in raw ``md``.
    """

    def __init__(
        self,
        run_schema: type[BaseModel] = BlueskyRun,
        triggers: Mapping[str, TriggerFn] | None = None,
    ) -> None:
        allowed_fields = set(run_schema.model_fields) | {
            f.alias for f in run_schema.model_fields.values() if f.alias
        }
        self.triggers = _TriggerMap(allowed_fields)
        if triggers:
            for field, callback in triggers.items():
                self.triggers[field] = callback

    def __call__(self, md: Mapping[str, Any]) -> dict[str, BaseModel | None]:
        """Execute matching field triggers on ``md`` and return projected common models."""
        commons: dict[str, BaseModel | None] = {}
        for field in self.triggers.keys() & md.keys():
            match result := self.triggers[field](md):
                case None:
                    continue
                case BaseModel():
                    commons[type(result).__name__] = result
                case Mapping():
                    commons |= dict(result)
                case list() | tuple() | set():
                    commons |= {type(model).__name__: model for model in result}
                case _:
                    raise ValueError(f"Trigger {field!r} returned uninterpretable result: {result!r}")
        return commons
