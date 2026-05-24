"""Tests for obase.template — load / validate / render_prompt."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from obase.template import (
    Template,
    TemplateError,
    TemplateValidationError,
    load,
    render_prompt,
    validate,
)


@pytest.fixture()
def valid_yaml(tmp_path: Path) -> Path:
    data = {
        "name": "finance_v1",
        "version": "1.0.0",
        "system_prompt": "You are a {role} specializing in {domain}.",
        "metadata": {"author": "wiki", "tags": ["quant"]},
    }
    p = tmp_path / "template.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    return p


# --- Test 1: Normal YAML load ---


def test_load_valid_yaml(valid_yaml: Path) -> None:
    t = load(valid_yaml)
    assert t.name == "finance_v1"
    assert t.version == "1.0.0"
    assert "{role}" in t.system_prompt
    assert t.metadata["author"] == "wiki"


# --- Test 2: Missing required field raises TemplateValidationError ---


def test_load_missing_required_field(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.dump({"name": "x", "version": "1.0.0"}), encoding="utf-8")
    with pytest.raises(TemplateValidationError, match="validation failed"):
        load(p)


# --- Test 3: Placeholder render ---


def test_render_prompt_success(valid_yaml: Path) -> None:
    t = load(valid_yaml)
    result = render_prompt(t, {"role": "analyst", "domain": "derivatives"})
    assert result == "You are a analyst specializing in derivatives."


# --- Test 4: Missing vars raises TemplateError ---


def test_render_prompt_missing_var(valid_yaml: Path) -> None:
    t = load(valid_yaml)
    with pytest.raises(TemplateError, match="Missing template variables"):
        render_prompt(t, {"role": "analyst"})  # missing 'domain'


# --- Test 5: Version validation (semver) ---


def test_version_validation_rejects_bad_format() -> None:
    with pytest.raises(Exception, match="semver"):
        Template(name="x", version="v1", system_prompt="hi", metadata={})


def test_version_validation_accepts_semver() -> None:
    t = Template(name="x", version="2.1.0", system_prompt="hi", metadata={})
    assert t.version == "2.1.0"


# --- Test 6: Large file load ---


def test_load_large_template(tmp_path: Path) -> None:
    big_prompt = "Line {n}\n" * 5000  # ~40KB
    data = {
        "name": "big-template",
        "version": "0.1.0",
        "system_prompt": big_prompt,
        "metadata": {},
    }
    p = tmp_path / "big.yaml"
    p.write_text(yaml.dump(data), encoding="utf-8")
    t = load(p)
    assert len(t.system_prompt) > 10000


# --- Test 7: Round-trip (load → dump → reload) ---


def test_round_trip(tmp_path: Path) -> None:
    original = Template(
        name="roundtrip",
        version="3.2.1",
        system_prompt="Hello {user}!",
        metadata={"key": "value"},
    )
    p = tmp_path / "rt.yaml"
    p.write_text(yaml.dump(original.model_dump()), encoding="utf-8")
    reloaded = load(p)
    assert reloaded == original


# --- Test 8: Name with whitespace rejected ---


def test_name_no_whitespace() -> None:
    with pytest.raises(Exception, match="whitespace"):
        Template(name="bad name", version="1.0.0", system_prompt="x", metadata={})


# --- Test 9: File not found ---


def test_load_file_not_found() -> None:
    with pytest.raises(TemplateError, match="not found"):
        load(Path("/nonexistent/template.yaml"))


# --- Test 10: validate() on valid template passes ---


def test_validate_valid_template() -> None:
    t = Template(name="ok", version="1.0.0", system_prompt="hi", metadata={})
    validate(t)  # should not raise


# --- Test 11: render with no placeholders ---


def test_render_no_placeholders() -> None:
    t = Template(name="plain", version="1.0.0", system_prompt="No vars here.", metadata={})
    assert render_prompt(t, {}) == "No vars here."


# --- Test 12: Invalid YAML syntax ---


def test_load_invalid_yaml_syntax(tmp_path: Path) -> None:
    p = tmp_path / "bad_syntax.yaml"
    p.write_text("name: [unclosed", encoding="utf-8")
    with pytest.raises(TemplateError, match="YAML parse error"):
        load(p)


# --- Test 13: YAML is not a mapping ---


def test_load_yaml_not_mapping(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(TemplateError, match="must be a mapping"):
        load(p)


# --- Test 14: validate() catches invalid template ---


def test_validate_catches_invalid() -> None:
    # Bypass validators with model_construct to create invalid instance
    t = Template.model_construct(name="bad name", version="nope", system_prompt="x", metadata={})
    with pytest.raises(TemplateValidationError, match="Validation failed"):
        validate(t)
