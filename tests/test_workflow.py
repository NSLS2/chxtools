from __future__ import annotations

import pytest
from pydantic import BaseModel

from chxtools.workflow import workflow


class SharedConfig(BaseModel):
    offset: int = 2


@pytest.fixture
def sample_workflow():
    @workflow(common=[SharedConfig], depends=[])
    def add_values(run, a: int, b: int, scale: float = 1.0):
        return (a + b + run["offset"]) * scale

    return add_values


def test_workflow_preserves_calling_behavior(sample_workflow):
    assert sample_workflow({"offset": 5}, 1, 2, scale=3) == 24


def test_workflow_schema_and_process_are_available(sample_workflow):
    schema = sample_workflow.schema
    assert schema.__name__.endswith("Schema")
    validated = schema.model_validate({"a": 3, "b": 4, "scale": 2.0})
    assert validated.model_dump() == {"a": 3, "b": 4, "scale": 2.0}

    result = sample_workflow.process(
        {"offset": 5},
        {"offset": 1},
        {"a": 3, "b": 4, "scale": 2.0},
    )
    assert result == 24


def test_workflow_excludes_direct_dependency_common_and_schema_fields():
    class SharedConfig(BaseModel):
        offset: int = 2

    @workflow(common=[SharedConfig], depends=[])
    def base_step(run, offset: int, a: int, b: int, scale: float = 1.0):
        return (a + b + offset + run["offset"]) * scale

    @workflow(common=[], depends=[base_step])
    def downstream_step(run, offset: int, c: int, scale: float = 1.0):
        return (c + offset + run["offset"]) * scale

    assert "offset" not in downstream_step.schema.model_fields
    assert set(downstream_step.schema.model_fields) == {"c"}


def test_workflow_excludes_common_fields_from_schema():
    class SharedConfig(BaseModel):
        offset: int = 2

    @workflow(common=[SharedConfig], depends=[])
    def add_values(run, offset: int, a: int, b: int, scale: float = 1.0):
        return (a + b + offset + run["offset"]) * scale

    schema = add_values.schema
    assert "offset" not in schema.model_fields
    assert set(schema.model_fields) == {"a", "b", "scale"}

    validated = schema.model_validate({"a": 3, "b": 4, "scale": 2.0})
    assert validated.model_dump() == {"a": 3, "b": 4, "scale": 2.0}
