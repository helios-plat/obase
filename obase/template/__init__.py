"""obase.template — YAML prompt template loading, validation, and rendering.

Example:
    >>> from pathlib import Path
    >>> from obase.template import load, validate, render_prompt
    >>> t = load(Path("templates/finance.yaml"))
    >>> validate(t)
    >>> prompt = render_prompt(t, {"role": "quant analyst"})
"""

from obase.template._impl import (
    Template,
    TemplateError,
    TemplateValidationError,
    load,
    render_prompt,
    validate,
)

__all__ = [
    "Template",
    "TemplateError",
    "TemplateValidationError",
    "load",
    "render_prompt",
    "validate",
]
