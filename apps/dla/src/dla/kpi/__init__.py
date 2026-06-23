"""KPI workbook (M7).

SMEs define KPIs — name, business definition, formula, grain, dimensions,
source tables, owner — that downstream agents and the recommender consume.
KPIs are always `sme-authored`; their `source_table_refs` are validated to
exist in the bundle before a KPI is written.
"""
