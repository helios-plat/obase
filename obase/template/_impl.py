"""obase.template._impl — Template load / validate / render implementation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, field_validator


class TemplateError(Exception):
    """Base error for template operations."""


class TemplateValidationError(TemplateError):
    """Template failed validation."""


class Template(BaseModel):
    """Prompt template with placeholder variables.

    Attributes:
        name: Template identifier (no whitespace allowed).
        version: Semantic version string.
        system_prompt: Prompt text, may contain ``{placeholder}`` variables.
        metadata: Arbitrary key-value metadata.

    Example:
        >>> t = Template(name="finance", version="1.0.0",
        ...     system_prompt="You are a {role}.", metadata={})
    """

    name: str
    version: str
    system_prompt: str
    metadata: dict[str, Any] = {}  # noqa: RUF012

    @field_validator("name")
    @classmethod
    def _name_no_whitespace(cls, v: str) -> str:
        if " " in v or "\t" in v or "\n" in v:
            raise ValueError("name must not contain whitespace")
        return v

    @field_validator("version")
    @classmethod
    def _version_format(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+\.\d+$", v):
            raise ValueError("version must be semver (e.g. '1.0.0')")
        return v


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def load(path: Path) -> Template:
    """Load a Template from a YAML file.

    Args:
        path: Path to the YAML template file.

    Returns:
        Parsed Template model.

    Raises:
        TemplateError: File not found or YAML parse failure.
        TemplateValidationError: YAML content fails Pydantic validation.

    Example:
        >>> from obase.template import load
        >>> t = load(Path("templates/finance.yaml"))
    """
    if not path.exists():
        raise TemplateError(f"Template file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TemplateError(f"YAML parse error: {exc}") from exc
    if not isinstance(data, dict):
        raise TemplateError("Template YAML must be a mapping")
    try:
        return Template.model_validate(data)
    except Exception as exc:
        raise TemplateValidationError(f"Template validation failed: {exc}") from exc


def validate(template: Template) -> None:
    """Validate a Template instance (re-run Pydantic validation).

    Args:
        template: Template to validate.

    Raises:
        TemplateValidationError: Validation failed.

    Example:
        >>> from obase.template import validate
        >>> validate(template)  # raises if invalid
    """
    try:
        Template.model_validate(template.model_dump())
    except Exception as exc:
        raise TemplateValidationError(f"Validation failed: {exc}") from exc


def render_prompt(template: Template, vars: dict[str, str]) -> str:
    """Render template system_prompt by substituting ``{placeholder}`` variables.

    Args:
        template: Template containing system_prompt with placeholders.
        vars: Mapping of placeholder names to values.

    Returns:
        Rendered prompt string.

    Raises:
        TemplateError: A placeholder in system_prompt has no matching var.

    Example:
        >>> render_prompt(template, {"role": "analyst"})
        'You are a analyst.'
    """
    placeholders = set(_PLACEHOLDER_RE.findall(template.system_prompt))
    missing = placeholders - set(vars.keys())
    if missing:
        raise TemplateError(f"Missing template variables: {sorted(missing)}")
    return template.system_prompt.format(**vars)
