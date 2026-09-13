import json
from typing import Any

from models import ParsedTurn, RelaxationSuggestion, SearchPreferences


_SYSTEM_PROMPT = """Classify the user's rental-search intent and return complete preferences.
Use search for a new search or an explicit preference change.
Use accept_relaxation only when the user agrees to a pending relaxation.
Use reject_relaxation when the user rejects a pending relaxation.
Use show_results when the user asks to see current listings without accepting or changing anything.
Use unknown when none applies. Never treat show_results as accepting a relaxation.
When accepting or previewing a pending relaxation, identify its one-based relaxation_number.
Use relaxation_number 1 when no number is specified and there is only one relevant suggestion.
Otherwise relaxation_number is null.
Use null for preferences not stated in a new search. Do not guess missing preferences.
Normalize Singapore district codes to uppercase and common room-type names to title case.
Interpret MTR as MRT. Set ranking_priority to price or mrt only when the user explicitly
prefers one; a numeric limit alone does not imply priority. Otherwise use balanced.
When current preferences are supplied, preserve them unless the user explicitly changes them.
"""


def parse_turn(
    text: str,
    model: Any,
    previous: SearchPreferences | None = None,
    relaxations: list[RelaxationSuggestion] | None = None,
    has_results: bool = False,
) -> ParsedTurn:
    """Use one structured model call to classify intent and merge preferences."""
    if not text.strip():
        raise ValueError("preference text cannot be empty")

    context = {
        "current_preferences": previous.model_dump() if previous else None,
        "matching_results_available": has_results,
        "pending_relaxations": relaxations or [],
    }
    message = (
        f"Conversation state: {json.dumps(context, ensure_ascii=False)}\n"
        f"User message: {text}"
    )
    parser = model.with_structured_output(ParsedTurn)
    return parser.invoke([("system", _SYSTEM_PROMPT), ("human", message)])
