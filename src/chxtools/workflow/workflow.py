"""
Minimal workflow decorator for generated parameter schemas and staged execution.

The intended usage is

    @workflow(common=[SharedConfig], depends=[other_workflow])
    def my_step(run, a: int, b: int, prefix: str):
        ...

The decorated object behaves like the original callable while also exposing:

- ``schema``: a pydantic model describing the non-run parameters
- ``process``: a convenience executor that accepts ``(run, common, schema)``
- ``depends`` and ``common``: metadata used to describe the workflow graph

This is intentionally lightweight: it focuses on validation and orchestration rather
than a full execution engine.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, create_model


class Workflow:
    """Callable wrapper returned by the workflow decorator."""

    def __init__(
        self,
        func: Callable[..., Any],
        common: Iterable[type[BaseModel]] | None = None,
        depends: Iterable[Workflow] | None = None,
    ) -> None:
        self.func = func
        self.common = set(common) if common is not None else set()
        self.depends = set(depends) if depends is not None else set()
        self.__name__ = func.__name__
        self.__qualname__ = func.__qualname__
        self.__module__ = func.__module__
        self.__doc__ = func.__doc__
        self.__wrapped__ = func
        self.schema = self._build_schema()

    def _build_schema(self) -> type[BaseModel]:
        signature = inspect.signature(self.func)
        fields: dict[str, Any] = {}
        excluded_names = {k for c in self.common for k in c.model_fields}

        dropout = {"self", "cls", "run", "bluesky_tiled_run", "common", "common_data", "schema"} | excluded_names
        for parameter in signature.parameters.values():
            if parameter.name in dropout:
                continue
            if parameter.kind in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }:
                continue

            annotation = parameter.annotation
            if annotation is inspect.Signature.empty:
                raise ValueError("workflow function is not sufficiently typed, "
                "please provide a type for all workflow parameters"
                "(special parameters run and bluesky_tiled_run are excluded from this)")
            if parameter.default is inspect.Signature.empty:
                fields[parameter.name] = (annotation, ...)
            else:
                fields[parameter.name] = (annotation, parameter.default)

        model_name = f"{self.func.__name__.capitalize()}Schema"
        if not fields:
            return create_model(model_name)
        return create_model(model_name, **fields)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Act as a wrapper for the underlying function."""
        return self.func(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Forward any fundamental calls to the underlying function itself."""
        return getattr(self.func, name)

    def process(
        self,
        run: Any,
        common_inst: Iterable[BaseModel],
        schema_inst: BaseModel,
        **kwargs: Any,
    ) -> Any:
        """Run the underlying function using validated schema values and shared config."""
        vals = (
            {k: v for c in common_inst for k, v in c.model_dump().items()} |
            kwargs |
            schema_inst.model_dump() |
            {'run': run, 'bluesky_tiled_run': run})
        signature = inspect.signature(self.func)
        d_params = {k: v for k, v in vals.items() if k in signature.parameters}
        return self.func(**d_params)


def workflow(
    func: Callable[..., Any] | None = None,
    common: Iterable[type[BaseModel]] | None = None,
    depends: Iterable[Workflow] | None = None,
) -> Workflow | Callable[[Callable[..., Any]], Workflow]:
    """Decorate a function as a workflow.

    This form supports both ``@workflow`` and ``@workflow(common=[...], depends=[...])``.
    """

    def decorator(target: Callable[..., Any]) -> Workflow:
        return Workflow(target, common=common, depends=depends)

    if func is None:
        return decorator
    return decorator(func)
