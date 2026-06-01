"""Prompt registry — versioned Jinja2 templates for every drafter prompt.

Each template lives at `src/dla/prompts/templates/<artifact>_v<N>.j2`. The
filename is also the `prompt_version` that gets stamped on every artifact
the prompt produces — so a re-run against a new prompt version can detect
the change and re-draft.
"""

from dla.prompts.registry import (
    PromptNotFoundError,
    available_prompts,
    load_template,
    render,
    template_path,
)

__all__ = [
    "PromptNotFoundError",
    "available_prompts",
    "load_template",
    "render",
    "template_path",
]
