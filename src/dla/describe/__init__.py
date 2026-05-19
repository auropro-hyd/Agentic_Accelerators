"""Describe engine — assembles grounding context, renders prompts, calls the
LLM gateway, writes description artifacts, and round-trips SME edits.
"""

from dla.describe.engine import (
    ArtifactNotFoundError,
    DescribePlan,
    DescribeReport,
    DescribeResult,
    LLMResponseParseError,
    ParsedDraft,
    build_column_context,
    build_description_payload,
    build_table_context,
    commit_sme_edits,
    compute_grounding_hash,
    describe_all,
    describe_column,
    describe_table,
    description_artifact_id,
    load_existing_description,
    parse_response,
    plan_column,
    plan_table,
    write_description,
)

__all__ = [
    "ArtifactNotFoundError",
    "DescribePlan",
    "DescribeReport",
    "DescribeResult",
    "LLMResponseParseError",
    "ParsedDraft",
    "build_column_context",
    "build_description_payload",
    "build_table_context",
    "commit_sme_edits",
    "compute_grounding_hash",
    "describe_all",
    "describe_column",
    "describe_table",
    "description_artifact_id",
    "load_existing_description",
    "parse_response",
    "plan_column",
    "plan_table",
    "write_description",
]
