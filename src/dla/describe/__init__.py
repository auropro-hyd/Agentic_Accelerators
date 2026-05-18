"""Describe engine — assembles grounding context, renders prompts, optionally
calls the LLM gateway, writes description artifacts.

Day-1: dry-run rendering only. Live calls land day-2.
"""

from dla.describe.engine import (
    ArtifactNotFoundError,
    DescribePlan,
    build_column_context,
    describe_column,
    plan_column,
)

__all__ = [
    "ArtifactNotFoundError",
    "DescribePlan",
    "build_column_context",
    "describe_column",
    "plan_column",
]
