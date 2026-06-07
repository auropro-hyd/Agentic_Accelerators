"""Local web UI for SME review (M4).

A stateless, server-rendered FastAPI + HTMX app over the bundle directory.
The markdown files remain the single source of truth — the UI reads them at
request time and (from M4 Increment B onward) writes edits back through the
same atomic bundle writer the CLI uses.
"""
