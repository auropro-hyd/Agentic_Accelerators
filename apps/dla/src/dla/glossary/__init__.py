"""Business glossary from recurring schema name tokens (M6).

`extractor` finds tokens that recur across table/column names; `definer`
drafts a plain-language definition per term via the LLM gateway and writes
`GlossaryEntry` artifacts. Confirmed entries feed back into description
generation (see `dla.glossary.feedback_loop`).
"""
