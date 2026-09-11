from typing import Any

from models import SearchPreferences


_SYSTEM_PROMPT = """Extract rental search preferences from the user's message.
Use null for anything not explicitly stated. Do not guess missing preferences.
Normalize Singapore district codes to uppercase and common room-type names to title case.
Interpret MTR as MRT. Set ranking_priority to price or mrt only when the user explicitly
prefers one; a numeric limit alone does not imply priority. Otherwise use balanced.
"""


def parse_preferences(text: str, model: Any) -> SearchPreferences:
    """Use a LangChain chat model to return validated search preferences."""
    if not text.strip():
        raise ValueError("preference text cannot be empty")

    parser = model.with_structured_output(SearchPreferences)
    return parser.invoke([("system", _SYSTEM_PROMPT), ("human", text)])
