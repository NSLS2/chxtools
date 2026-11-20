"""
Subpackage to allow exportability of workflows.

Including behavior for:
- analysis funcs as remote workflows
- RE based triggering mechanisms.
"""
from .manager import WorkflowManager
from .projection import MDProjector
from .workflow import workflow

__all__ = [
    "MDProjector",
    "WorkflowManager",
    "workflow",
]
