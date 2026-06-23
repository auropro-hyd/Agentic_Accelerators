"""Versioned Jinja2 prompt registry.

Templates live next to this module at `templates/<name>.j2`. The template
filename without the `.j2` extension is the `prompt_version` stamped onto
artifacts produced from it — e.g. loading `column_v1.j2` gives a template
whose `prompt_version` is `column_v1`.

Rendering is deterministic given the same context — Jinja2 autoescape is
disabled (we generate plain text prompts, not HTML) and templates use no
random sources.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template, TemplateNotFound

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


class PromptNotFoundError(KeyError):
    """Raised when a requested template is not present on disk."""


def template_path(name: str) -> Path:
    """Return the on-disk path for the given prompt name (e.g. `column_v1`)."""
    return _TEMPLATES_DIR / f"{name}.j2"


def available_prompts() -> list[str]:
    """List every `<name>` for which a `<name>.j2` template exists, sorted."""
    if not _TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in _TEMPLATES_DIR.glob("*.j2"))


def load_template(name: str) -> Template:
    """Return the compiled Jinja2 `Template` object for the given name.

    Raises:
        PromptNotFoundError: when no `<name>.j2` exists.
    """
    try:
        return _ENV.get_template(f"{name}.j2")
    except TemplateNotFound as exc:
        raise PromptNotFoundError(
            f"Prompt template {name!r} not found in {_TEMPLATES_DIR}. "
            f"Available: {available_prompts()}"
        ) from exc


def render(name: str, context: dict[str, Any]) -> str:
    """Render a template by name with the given context dictionary.

    `StrictUndefined` means any missing context key is an immediate
    `UndefinedError` rather than a silently empty string — so prompts can't
    silently lose grounding signals.
    """
    template = load_template(name)
    return template.render(**context)
