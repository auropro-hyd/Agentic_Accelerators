"""Snowflake-schema detector (T135).

A snowflake extends a star: a dimension table (referenced by a fact) itself
references a further table — i.e. the dimensions are normalized.
"""

from __future__ import annotations

from dla.bundle.schema import PatternType
from dla.patterns.base import DetectedPattern, SchemaGraph
from dla.patterns.star import detect as detect_star


def detect(graph: SchemaGraph) -> list[DetectedPattern]:
    out: list[DetectedPattern] = []
    for star in detect_star(graph):
        fact = star.participants["fact_table"]
        for dim in star.participants["dimensions"]:
            sub = [t for t in graph.fk_targets.get(dim, []) if t != fact]
            if sub:
                out.append(
                    DetectedPattern(
                        pattern_type=PatternType.SNOWFLAKE_SCHEMA,
                        participants={
                            "fact_table": fact,
                            "dimension": dim,
                            "sub_dimensions": sorted(sub),
                        },
                        explanation=(
                            f"Dimension {graph.tables[dim].name} is normalized — it "
                            f"references {len(sub)} further table(s), snowflaking the star."
                        ),
                    )
                )
    return out
