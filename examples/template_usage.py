"""Example: obase.template usage."""

from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from obase.template import Template, load, render_prompt, validate

# 1. Create a template YAML
template_data = {
    "name": "quant_finance_v1",
    "version": "1.0.0",
    "system_prompt": (
        "You are a {role} specializing in {domain}. "
        "Generate content for a {duration}-second video."
    ),
    "metadata": {"author": "wiki", "industry": "finance"},
}

with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.dump(template_data, f)
    path = Path(f.name)

# 2. Load
template = load(path)
print(f"Loaded: {template.name} v{template.version}")

# 3. Validate
validate(template)
print("Validation passed.")

# 4. Render
prompt = render_prompt(template, {"role": "quant analyst", "domain": "derivatives", "duration": "60"})
print(f"Rendered: {prompt}")

# 5. Programmatic construction
t2 = Template(name="education_v1", version="2.0.0", system_prompt="Teach {topic}.", metadata={})
print(f"Rendered t2: {render_prompt(t2, {'topic': 'calculus'})}")
