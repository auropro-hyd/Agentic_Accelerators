"""Dimension hierarchies — SME-authored drill-down paths (M7 extension).

A hierarchy records the drill-down order of one dimension (e.g. date:
year → quarter → month), each level mapped to a discovered column. Downstream
consumers (the knowledge-representation layer) read hierarchies to offer
"executive summary → specific point" navigation without inventing paths.
"""

from dla.hierarchy.artifacts import (
    HierarchyValidationError,
    hierarchy_artifact_id,
    load_hierarchy,
    save_hierarchy,
)

__all__ = [
    "HierarchyValidationError",
    "hierarchy_artifact_id",
    "load_hierarchy",
    "save_hierarchy",
]
