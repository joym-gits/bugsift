"""Jinja2 prompt loader. Prompts are co-located with the agent module so they
ride along with the code that calls them. Autoescape is OFF — prompts are
plain text for the model, not HTML.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        keep_trailing_newline=False,
    )


def render(template_name: str, **context: Any) -> str:
    return _env().get_template(template_name).render(**context)
