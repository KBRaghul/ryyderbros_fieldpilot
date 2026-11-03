"""Scope guards shared by the single agent and the multi-agent system.

They run in code before any LLM call, so both modes refuse the same questions the same way.
"""
import re

from app.tools.sentinel import FIELDS_DIR


def other_field_mentioned(question, field_name):
    """Return another demo field's county if the question asks about it, else None.
    Requires 'county', 'field', 'corn', or 'cotton' after the name, so 'apply limestone' does not match."""
    q = question.lower()
    this_county = field_name.split("_")[0]
    for p in FIELDS_DIR.glob("*.geojson"):
        county = p.stem.split("_")[0]
        if county != this_county and re.search(rf"\b{county}\s+(county|field|corn|cotton)\b", q):
            return county.title()
    return None


def scope_reply(question, field_name, field):
    """A fixed answer when the question is outside this field's scope, else None."""
    other = other_field_mentioned(question, field_name)
    if other:
        return (f"I can only answer about the {field['crop']} field in {field['county']}. "
                f"To ask about the {other} County field, select it from the field list.")
    return None
