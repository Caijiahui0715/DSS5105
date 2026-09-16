import json
from datetime import date
from typing import Any

from models import ParsedTurn, RelaxationSuggestion, SearchPreferences


_SYSTEM_PROMPT = """Classify the user's rental-search intent and return complete preferences.
Use search for a new search or an explicit preference change.
Use compare_shortlist when the user asks to compare shortlisted listings or two or more
explicit listing IDs. Set compare_listing_ids when explicit IDs are provided; otherwise
leave it empty to compare the whole shortlist.
Use show_listing_details when the user asks for more information about one listing.
Set detail_listing_number for a displayed position such as "the second listing". Leave it
null for "this listing"; the graph resolves it only when exactly one listing was shown.
Use accept_relaxation only when the user agrees to a pending relaxation.
Use reject_relaxation when the user rejects a pending relaxation.
Use reject_results when the user rejects shown listings without changing preferences.
Use shortlist_listing when the user wants to save or consider an already shown listing.
Use remove_shortlisted_listing when the user no longer wants a listing that they saved,
including phrases such as "the one I just added to the shortlist".
Use show_shortlist when the user asks to view saved, shortlisted, or candidate listings.
Use show_results when the user asks to see current listings without accepting or changing anything.
Use unknown when none applies. Never treat show_results as accepting a relaxation.
Set reject_all_shown when the user rejects "this listing", "these listings", or all shown results.
Use rejected_listing_numbers for specific displayed positions such as "the second listing".
Set shortlist_listing_numbers for every stated displayed position, including plural or range
requests such as "the first two" -> [1, 2]. Set shortlist_listing_ids for every explicit
listing ID such as "S010 and S009". Leave both lists empty for words such as "this listing";
the graph will resolve it only when exactly one listing was shown.
Set shortlisted_listing_number from shortlisted_listing_ids_in_order when removing a saved
listing. Leave it null for "the saved listing"; the graph resolves it only when exactly one
listing is shortlisted.
If the user rejects listings and changes a preference in the same message, return the updated
preferences and the rejection fields together; use search as the intent.
When accepting or previewing a pending relaxation, identify its one-based relaxation_number.
Use relaxation_number 1 when no number is specified and there is only one relevant suggestion.
Otherwise relaxation_number is null.
Use null for preferences not stated in a new search. Do not guess missing preferences.
For every budget explicitly stated in this turn, set budget_amount to the number and
budget_currency to an uppercase ISO 4217 code. When no currency is stated, including
the generic Chinese word "元", default to SGD. Normalize 新币/新加坡元 to SGD and
人民币/RMB to CNY. A bare "$" or "¥" is ambiguous: set budget_currency null and do
not guess. For SGD budgets, also set preferences.max_price_sgd to budget_amount. For
foreign or ambiguous budgets, do not put the unconverted amount into max_price_sgd;
the graph will convert it. Leave budget_amount and budget_currency null when the user
does not state a new budget in this turn.
Listing IDs may be synthetic IDs such as S010 or real PropertyGuru IDs containing 8-9
digits. Never treat a budget, date, or MRT duration as a listing ID.
Normalize Singapore district codes to uppercase and room types to snake_case values such
as common_room, master_room, shared_room, studio, or room_unspecified.
Set rental_scope to entire_unit for 整租 or a whole unit, and room for 合租, 单间 or a room;
never encode rental scope as room_type.
Set property_types only when a property type is named: 公寓, condo or private apartment means
condominium, executive_condominium, apartment and walk_up_apartment; 组屋 or HDB means hdb_flat;
有地住宅 or landed means the house types. Property type does not decide rental_scope.
The suggested_refinement_fields are optional, never search blockers. When room_type is
suggested and the user says every/any room type is acceptable, keep room_type null, set
room_type_flexible true, and use search. Set it false when a specific room type is chosen.
Return move_in_date as YYYY-MM-DD. Resolve relative or yearless dates using the supplied
current date. Set move_in_flexible only when the user explicitly says the date is flexible.
Set cooking_required only when cooking is a requirement, not merely mentioned.
Set min_bedrooms when the user gives a minimum bedroom count. Set occupant_count to the
number of people who need to stay; tenant_count_reported is the advertised maximum allowed
occupancy. The dataset has no reliable platform-verification field, so never invent or
preserve a verified-only preference.
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
    shown_listing_ids: list[str] | None = None,
    shortlisted_listing_ids: list[str] | None = None,
    suggested_refinement_fields: list[str] | None = None,
) -> ParsedTurn:
    """Use one structured model call to classify intent and merge preferences."""
    if not text.strip():
        raise ValueError("preference text cannot be empty")

    context = {
        "today": date.today().isoformat(),
        "current_preferences": previous.model_dump(mode="json") if previous else None,
        "matching_results_available": has_results,
        "shown_listing_ids_in_display_order": shown_listing_ids or [],
        "shortlisted_listing_ids_in_order": shortlisted_listing_ids or [],
        "suggested_refinement_fields": suggested_refinement_fields or [],
        "pending_relaxations": relaxations or [],
    }
    message = (
        f"Conversation state: {json.dumps(context, ensure_ascii=False)}\n"
        f"User message: {text}"
    )
    parser = model.with_structured_output(ParsedTurn)
    return parser.invoke([("system", _SYSTEM_PROMPT), ("human", message)])
