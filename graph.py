import re
from decimal import Decimal, InvalidOperation
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from decision import diagnose_conditions, explain_listing, load_source_evidence, occupant_rules, search_with_unknowns
from exchange import CurrencyConversionError, convert_to_sgd
from faculties import find_faculty
from group_db import Database
from models import (
    Listing,
    ListingCheckSummary,
    RankingResult,
    RelaxationSuggestion,
    ResponseLanguage,
    RestrictionSummary,
    SearchPreferences,
    UserIntent,
)
from parser import parse_turn
from response import (
    _check_summary_text,
    render_budget_conversion,
    render_comparison,
    render_decision_context,
    render_intent_response,
    render_listing_details,
    render_listing_explanation,
    render_needs_confirmation,
    render_no_faculty,
    render_occupants,
    render_relaxation_preview,
    render_response,
)
from tools import (
    analyze_relaxations,
    check_listing_url,
    extract_restrictions,
    get_listings_by_ids,
    own_commute_needed,
    rank_listings,
    search_listings,
    validate_ranked_listings,
)


class AgentState(TypedDict, total=False):
    message: str
    # The user's NUS faculty, from the caller (an account setting); copied into the preferences each turn.
    faculty: str | None
    response_language: ResponseLanguage
    budget_amount: int | None
    budget_currency: str | None
    budget_months: int | None
    budget_conversion: dict[str, int | str] | None
    budget_conversion_error: str | None
    intent: UserIntent
    relaxation_number: int | None
    reject_all_shown: bool
    rejected_listing_numbers: list[int]
    shortlist_listing_numbers: list[int]
    shortlist_listing_ids: list[str]
    compare_listing_ids: list[str]
    detail_listing_id: str | None
    detail_listing_number: int | None
    shortlisted_listing_number: int | None
    preferences: SearchPreferences
    listings: list[Listing]
    # Listings that meet every known condition but do not state some requirement, as the agent shows them.
    pending_listings: list[Listing]
    confirm_listings: list[RankingResult]
    confirm_check_summary: ListingCheckSummary | None
    # Without strict matches: what dropping each condition alone would yield (decision.diagnose_conditions).
    decision_context: list[dict]
    # What the number of people changed this turn (decision.occupant_rules), shown after the results.
    occupant_note: dict | None
    restrictions: dict[str, RestrictionSummary]
    ranked_listings: list[RankingResult]
    listing_check_summary: ListingCheckSummary | None
    relaxations: list[RelaxationSuggestion]
    shown_listing_ids: list[str]
    excluded_listing_ids: list[str]
    shortlisted_listing_ids: list[str]
    last_excluded_listing_ids: list[str]
    missing_preferences: list[str]
    response_draft: str
    response: str
    # This turn's replies that failed the fact check, and other steps worth showing with --trace.
    trace: list[str]


_ACCEPT_FIRST = {
    "yes",
    "ok",
    "okay",
    "可以",
    "可以的",
    "好",
    "好的",
    "行",
    "同意",
    "接受",
    "接受建议",
    "接受第一个建议",
}

_RESPONSE_PROMPT = """Reply only in {language}, using natural, concise language like a helpful rental adviser,
not a form or database dump. The verified draft is the only source of truth. Do not
copy its stock opening or field labels mechanically: answer the user's intent directly
and, when listings exist, briefly point out useful trade-offs already visible in the
draft before presenting the facts in an easy-to-scan form. Preserve every listing ID,
price, MRT value, ranking order, restriction, warning, and whether a relaxation is
only a preview. Preserve any currency-conversion amount, rate, and rate date. Do not
invent or change listings, facts, availability, amenities, currencies, or user choices.
Distinguish database matches, checked/displayable listings, and unchecked candidates.
An active URL does not confirm rental availability; unknown does not mean inactive.
When information is missing or uncertain, say so plainly. This agent
cannot contact landlords, confirm future availability, reserve listings, or arrange
viewings, so never claim or offer to do those things. Only suggest actions the agent
can perform: search, refine conditions, show details, shortlist, or compare. Return
only the user-facing reply.
"""

_UNSUPPORTED_ACTION_OFFER = re.compile(
    r"(?:需要我|要我|我可以|我能|我来|让我).*?"
    r"(?:联系.{0,8}(?:房东|发布方)|"
    r"(?:确认|核实).{0,24}(?:入住|空房|可租|档期)|"
    r"预约.{0,8}(?:看房|房源)|(?:预订|预定|保留).{0,8}(?:房源|房间))"
)
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_OFFER = r"\b(?:I can(?!not|'t|’t)|I could(?! not|n't|n’t)|I will(?! not)|I'll(?! not)|let me(?! know)|shall I|want me to)\b[^.?!\n]{0,60}"
_UNSUPPORTED_OFFER_EN = re.compile(
    _OFFER + r"\b(?:contact|call|email|reach out|book|schedule|arrange|reserve|hold|confirm (?:the )?availability)",
    re.IGNORECASE,
)
_NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
_CLAIMED_NUMBER = re.compile(
    rf"(?:S\$|SGD|\$)\s*({_NUMBER})|({_NUMBER})\s*(?:新币|新加坡元|SGD|元|分钟|mins?\b|minutes?\b|套|listings?\b)",
    re.IGNORECASE,
)

_REFINEMENT_LABELS = {
    "zh": {
        "max_price_sgd": "每月最高预算",
        "rental_scope": "想整租还是合租（租一个房间）",
        "room_type": "房型（例如 Common Room、Master Room 或 Shared Room）",
        "move_in_date": "计划入住时间",
    },
    "en": {
        "max_price_sgd": "your maximum monthly budget",
        "rental_scope": "whether you want a whole unit or a room in a shared home",
        "room_type": "a room type such as Common Room, Master Room, or Shared Room",
        "move_in_date": "your planned move-in date",
    },
}


def build_graph(
    connection: Database,
    model: Any,
    checkpointer=None,
    listing_checker=check_listing_url,
):
    def validated(ranked: list[RankingResult]) -> list[RankingResult]:
        return validate_ranked_listings(
            connection,
            ranked,
            listing_checker,
            candidate_limit=len(ranked),
        )["ranked_listings"]

    def begin_turn_node(state: AgentState):
        faculty = _faculty(state.get("faculty"))
        update: AgentState = {
            "response_language": _response_language(
                state["message"], state.get("response_language")
            ),
            "faculty": faculty,
            "occupant_note": None,
            "trace": [],
        }
        if state.get("preferences"):
            update["preferences"] = state["preferences"].model_copy(update={"faculty": faculty})
        return update

    def interpret_node(state: AgentState):
        previous = state.get("preferences")
        relaxations = state.get("relaxations", [])
        explicit_ids = _listing_ids_in(state["message"])
        explains = _asks_to_explain(state["message"])
        if explicit_ids and (explains or _asks_to_show_listing_details(state["message"])):
            return {
                "intent": "explain_listing" if explains else "show_listing_details",
                "detail_listing_id": explicit_ids[0],
                "detail_listing_number": None,
                "relaxation_number": None,
                "reject_all_shown": False,
                "rejected_listing_numbers": [],
                "shortlist_listing_numbers": [],
                "shortlist_listing_ids": [],
                "compare_listing_ids": [],
                "shortlisted_listing_number": None,
                "last_excluded_listing_ids": [],
            }
        if _asks_to_compare_listings(state["message"]):
            return {
                "intent": "compare_shortlist",
                "compare_listing_ids": _listing_ids_in(state["message"]),
                "detail_listing_id": None,
                "detail_listing_number": None,
                "relaxation_number": None,
                "reject_all_shown": False,
                "rejected_listing_numbers": [],
                "shortlist_listing_numbers": [],
                "shortlist_listing_ids": [],
                "shortlisted_listing_number": None,
                "last_excluded_listing_ids": [],
            }
        if _asks_to_show_shortlist(state["message"]):
            return {
                "intent": "show_shortlist",
                "relaxation_number": None,
                "reject_all_shown": False,
                "rejected_listing_numbers": [],
                "shortlist_listing_numbers": [],
                "shortlist_listing_ids": [],
                "compare_listing_ids": [],
                "detail_listing_id": None,
                "detail_listing_number": None,
                "shortlisted_listing_number": None,
                "last_excluded_listing_ids": [],
            }
        if previous and relaxations and _accepts_first(state["message"]):
            return {
                "intent": "accept_relaxation",
                "relaxation_number": 1,
                "reject_all_shown": False,
                "rejected_listing_numbers": [],
                "shortlist_listing_numbers": [],
                "shortlist_listing_ids": [],
                "compare_listing_ids": [],
                "detail_listing_id": None,
                "detail_listing_number": None,
                "shortlisted_listing_number": None,
                "last_excluded_listing_ids": [],
            }

        turn = parse_turn(
            state["message"],
            model,
            previous,
            relaxations,
            bool(state.get("ranked_listings") or state.get("shown_listing_ids")),
            state.get("shown_listing_ids"),
            state.get("shortlisted_listing_ids"),
            state.get("missing_preferences"),
            state.get("faculty"),
        )
        current = previous or SearchPreferences()
        # Commute times here are to the faculty only; there is no other destination in the workflow.
        preferences = turn.preferences.model_copy(
            update={"faculty": state.get("faculty"), "other_destination": None, "max_other_commute_minutes": None}
        )
        changes = {
            field: getattr(preferences, field)
            for field in SearchPreferences.model_fields
            if getattr(preferences, field) != getattr(current, field)
        }
        # The same rules as the agent for the number of people and the rental type.
        extra, occupant_note = occupant_rules(current, changes)
        if extra:
            preferences = preferences.model_copy(update=extra)
        return {
            "intent": turn.intent,
            "relaxation_number": turn.relaxation_number,
            "reject_all_shown": turn.reject_all_shown,
            "rejected_listing_numbers": turn.rejected_listing_numbers,
            "shortlist_listing_numbers": turn.shortlist_listing_numbers,
            "shortlist_listing_ids": (
                _listing_ids_in(state["message"]) or turn.shortlist_listing_ids
                if turn.intent == "shortlist_listing"
                else []
            ),
            "compare_listing_ids": (
                _listing_ids_in(state["message"]) or turn.compare_listing_ids
                if turn.intent == "compare_shortlist"
                else []
            ),
            "detail_listing_id": (
                explicit_ids[0]
                if turn.intent in {"show_listing_details", "explain_listing"} and explicit_ids
                else None
            ),
            "detail_listing_number": turn.detail_listing_number,
            "budget_amount": turn.budget_amount,
            "budget_currency": turn.budget_currency,
            "budget_months": turn.budget_months,
            "shortlisted_listing_number": turn.shortlisted_listing_number,
            "last_excluded_listing_ids": [],
            "preferences": preferences,
            "occupant_note": occupant_note,
        }

    def route_after_interpret(state: AgentState):
        if _selected_rejection_ids(state):
            return "reject"
        if state["intent"] == "reject_results":
            return "conversation"
        if state["intent"] == "shortlist_listing":
            return "shortlist"
        if state["intent"] == "remove_shortlisted_listing":
            return "remove_shortlist"
        if state["intent"] == "show_shortlist":
            return "show_shortlist"
        if state["intent"] == "compare_shortlist":
            return "compare_shortlist"
        if state["intent"] == "show_listing_details":
            return "show_listing_details"
        if state["intent"] == "explain_listing":
            return "explain_listing"
        if state["intent"] == "search":
            return (
                "search"
                if state.get("budget_amount") is not None
                or _has_search_criteria(state["preferences"])
                else "clarify"
            )
        shown = state.get("ranked_listings") or state.get("confirm_listings")
        if (
            state["intent"] == "show_results"
            and not shown
            and not _has_search_criteria(state["preferences"])
        ):
            return "clarify"
        index = (state.get("relaxation_number") or 1) - 1
        if state["intent"] == "accept_relaxation":
            if 0 <= index < len(state.get("relaxations", [])):
                return "accept"
        if state["intent"] == "show_results" and not shown:
            if 0 <= index < len(state.get("relaxations", [])):
                return "preview"
        return "conversation"

    def apply_rejections_node(state: AgentState):
        # ponytail: exclusions last for this in-memory session; add an undo intent if needed.
        selected = _selected_rejection_ids(state)
        excluded = list(
            dict.fromkeys(
                [
                    *state.get("excluded_listing_ids", []),
                    *selected,
                ]
            )
        )
        return {
            "excluded_listing_ids": excluded,
            "last_excluded_listing_ids": selected,
            "shortlisted_listing_ids": [
                listing_id
                for listing_id in state.get("shortlisted_listing_ids", [])
                if listing_id not in selected
            ],
        }

    def apply_relaxation_node(state: AgentState):
        index = (state.get("relaxation_number") or 1) - 1
        suggestion = state["relaxations"][index]
        update: AgentState = {
            "preferences": state["preferences"].model_copy(
                update={suggestion["field"]: suggestion["suggested"]}
            )
        }
        if suggestion["field"] == "max_price_sgd":
            update["budget_conversion"] = None
        return update

    def shortlist_node(state: AgentState):
        shown = state.get("shown_listing_ids", [])
        numbers = state.get("shortlist_listing_numbers", [])
        explicit_ids = [
            listing_id.strip().upper()
            for listing_id in state.get("shortlist_listing_ids", [])
            if listing_id.strip()
        ]
        if not numbers and not explicit_ids and len(shown) == 1:
            numbers = [1]
        if not numbers and not explicit_ids and not shown:
            return {
                "response_draft": _text(
                    state,
                    "目前没有已展示的房源。你也可以直接提供房源编号，例如 S010。",
                    "There are no displayed listings. You can provide a listing ID directly, such as S010.",
                )
            }
        if not numbers and not explicit_ids:
            return {
                "response_draft": _text(
                    state,
                    f"目前展示了 {len(shown)} 套房源，请告诉我想收藏哪几套或房源编号。",
                    f"There are {len(shown)} displayed listings. Tell me which positions or listing IDs to shortlist.",
                )
            }

        invalid_numbers = [number for number in numbers if not 1 <= number <= len(shown)]
        requested_ids = list(
            dict.fromkeys(
                [
                    *(shown[number - 1] for number in numbers if number not in invalid_numbers),
                    *explicit_ids,
                ]
            )
        )
        valid_ids = [
            listing["listing_id"]
            for listing in get_listings_by_ids(connection, requested_ids)
        ]
        missing_ids = [listing_id for listing_id in requested_ids if listing_id not in valid_ids]
        if not valid_ids:
            problems = []
            if invalid_numbers:
                problems.append(
                    _text(
                        state,
                        f"无效序号：{', '.join(map(str, invalid_numbers))}",
                        f"Invalid positions: {', '.join(map(str, invalid_numbers))}",
                    )
                )
            if missing_ids:
                problems.append(
                    _text(
                        state,
                        f"未找到房源：{'、'.join(missing_ids)}",
                        f"Listings not found: {', '.join(missing_ids)}",
                    )
                )
            return {
                "response_draft": ("；" if _language(state) == "zh" else "; ").join(problems)
                or _text(state, "没有找到可加入的房源。", "No listings could be added.")
            }

        shortlisted = list(
            dict.fromkeys([*state.get("shortlisted_listing_ids", []), *valid_ids])
        )
        response = _text(
            state,
            f"已将房源 {'、'.join(valid_ids)} 加入候选清单。",
            f"Added listings {', '.join(valid_ids)} to your shortlist.",
        )
        if invalid_numbers:
            response += _text(
                state,
                f" 无效序号已忽略：{', '.join(map(str, invalid_numbers))}。",
                f" Invalid positions ignored: {', '.join(map(str, invalid_numbers))}.",
            )
        if missing_ids:
            response += _text(
                state,
                f" 未找到并已忽略：{'、'.join(missing_ids)}。",
                f" Not found and ignored: {', '.join(missing_ids)}.",
            )
        return {
            "shortlisted_listing_ids": shortlisted,
            "excluded_listing_ids": [
                listing_id
                for listing_id in state.get("excluded_listing_ids", [])
                if listing_id not in valid_ids
            ],
            "response_draft": response,
        }

    def remove_shortlist_node(state: AgentState):
        shortlisted = state.get("shortlisted_listing_ids", [])
        number = state.get("shortlisted_listing_number")
        if not shortlisted:
            return {"response_draft": _text(state, "候选清单目前是空的。", "Your shortlist is empty.")}
        if number is None and len(shortlisted) > 1:
            return {
                "response_draft": _text(
                    state,
                    f"候选清单里有 {len(shortlisted)} 套房源，请告诉我不再考虑第几套。",
                    f"Your shortlist has {len(shortlisted)} listings. Tell me which position to remove.",
                )
            }

        index = (number or 1) - 1
        if not 0 <= index < len(shortlisted):
            return {
                "response_draft": _text(
                    state,
                    f"请提供 1 到 {len(shortlisted)} 之间的候选房源序号。",
                    f"Please provide a shortlist position from 1 to {len(shortlisted)}.",
                )
            }

        listing_id = shortlisted[index]
        ranked = [
            item
            for item in state.get("ranked_listings", [])
            if item["listing"]["listing_id"] != listing_id
        ]
        response = _text(
            state,
            f"已将房源 {listing_id} 从候选清单移除，并从当前搜索结果排除。",
            f"Removed listing {listing_id} from your shortlist and excluded it from the current search.",
        )
        response += (
            f"\n\n{render_response(ranked, state.get('restrictions'), language=_language(state))}"
            if ranked
            else _text(state, "\n\n当前没有剩余的匹配房源。", "\n\nThere are no matching listings left.")
        )
        return {
            "shortlisted_listing_ids": shortlisted[:index] + shortlisted[index + 1 :],
            "excluded_listing_ids": list(
                dict.fromkeys([*state.get("excluded_listing_ids", []), listing_id])
            ),
            "last_excluded_listing_ids": [listing_id],
            "listings": [
                listing
                for listing in state.get("listings", [])
                if listing["listing_id"] != listing_id
            ],
            "ranked_listings": ranked,
            "shown_listing_ids": _shown_listing_ids(ranked),
            "response_draft": response,
        }

    def show_shortlist_node(state: AgentState):
        listing_ids = state.get("shortlisted_listing_ids", [])
        if not listing_ids:
            return {"response_draft": _text(state, "候选清单目前是空的。", "Your shortlist is empty.")}

        listings = get_listings_by_ids(connection, listing_ids)
        ranked_by_id = {
            item["listing"]["listing_id"]: item
            for item in validated(rank_listings(listings, state["preferences"]))
        }
        ranked = [ranked_by_id[listing_id] for listing_id in listing_ids if listing_id in ranked_by_id]
        restrictions = {
            listing["listing_id"]: extract_restrictions(listing)
            for listing in listings
        }
        return {
            "response_draft": render_response(
                ranked,
                restrictions,
                heading=_text(
                    state,
                    f"候选清单共有 {len(ranked)} 套房源：",
                    f"Your shortlist contains {len(ranked)} listings:",
                ),
                limit=len(ranked),
                language=_language(state),
            ),
            "shown_listing_ids": [
                item["listing"]["listing_id"] for item in ranked
            ],
        }

    def compare_shortlist_node(state: AgentState):
        requested_ids = state.get("compare_listing_ids") or state.get(
            "shortlisted_listing_ids", []
        )
        listings = get_listings_by_ids(connection, requested_ids)
        if len(listings) < 2:
            return {
                "response_draft": _text(
                    state,
                    "至少需要两套可用房源才能进行比较，请先继续添加候选房源。",
                    "At least two available listings are needed for a comparison. Add more listings to your shortlist first.",
                )
            }

        restrictions = {
            listing["listing_id"]: extract_restrictions(listing)
            for listing in listings
        }
        ranked = validated(rank_listings(listings, _preferences(state)))
        return {
            "response_draft": render_comparison(
                ranked, restrictions, _language(state)
            ),
            "shown_listing_ids": [
                item["listing"]["listing_id"] for item in ranked
            ],
        }

    def chosen_listing(state: AgentState) -> tuple[str | None, str | None]:
        """The listing a details or explain request means, or else the draft asking which one."""
        shown = state.get("shown_listing_ids", [])
        listing_id = state.get("detail_listing_id")
        number = state.get("detail_listing_number")
        if listing_id is None and number is not None:
            if not 1 <= number <= len(shown):
                return None, _text(
                    state,
                    f"请提供 1 到 {len(shown)} 之间的房源序号。"
                    if shown
                    else "目前没有已展示的房源，请直接提供房源编号。",
                    f"Please provide a listing position from 1 to {len(shown)}."
                    if shown
                    else "There are no displayed listings. Please provide a listing ID directly.",
                )
            listing_id = shown[number - 1]
        if listing_id is None and len(shown) == 1:
            listing_id = shown[0]
        if listing_id is None:
            return None, _text(
                state,
                f"目前展示了 {len(shown)} 套房源，请告诉我想查看第几套。"
                if shown
                else "目前没有已展示的房源，请直接提供房源编号，例如 S010。",
                f"There are {len(shown)} displayed listings. Tell me which position to view."
                if shown
                else "There are no displayed listings. Please provide a listing ID directly, such as S010.",
            )
        return listing_id, None

    def not_found(state: AgentState, listing_id: str) -> AgentState:
        return {"response_draft": _text(state, f"没有找到房源 {listing_id}。", f"Listing {listing_id} was not found.")}

    def show_listing_details_node(state: AgentState):
        listing_id, question = chosen_listing(state)
        if question:
            return {"response_draft": question}
        listings = get_listings_by_ids(connection, [listing_id])
        if not listings:
            return not_found(state, listing_id)
        ranked = validated(rank_listings(listings, _preferences(state)))
        if not ranked:
            return {
                "response_draft": _text(
                    state,
                    f"房源 {listing_id} 的原链接已经失效，暂不继续推荐。",
                    f"Listing {listing_id} is no longer available at its original link and will not be recommended.",
                )
            }
        listing = ranked[0]["listing"]
        return {
            "response_draft": render_listing_details(
                listing,
                extract_restrictions(listing),
                _language(state),
                ranked[0].get("commute"),
            ),
            "shown_listing_ids": [listing_id],
        }

    def explain_listing_node(state: AgentState):
        # As the agent's explain tool: ranking factors, each condition and where each fact comes from.
        listing_id, question = chosen_listing(state)
        if question:
            return {"response_draft": question}
        listings = get_listings_by_ids(connection, [listing_id])
        if not listings:
            return not_found(state, listing_id)
        listing = listings[0]
        explanation = explain_listing(listing, _preferences(state), load_source_evidence().get(listing["listing_id"]))
        return {"response_draft": render_listing_explanation(explanation, _language(state))}

    def clarification_node(state: AgentState):
        missing = _open_preferences(state["preferences"])
        return {
            "missing_preferences": missing,
            "response_draft": _text(
                state,
                "请至少告诉我一个搜索条件，例如每月预算、地区（如 D05）、房型或可接受的 MRT 步行时间。",
                "Please provide at least one search criterion, such as your monthly budget, district (for example D05), room type, or acceptable MRT walking time.",
            ),
        }

    def normalize_budget_node(state: AgentState):
        amount = state.get("budget_amount")
        currency = state.get("budget_currency")
        if amount is None:
            return {"budget_conversion_error": None}
        if currency is None:
            return {
                "budget_conversion_error": "ambiguous_currency",
                "response_draft": _text(
                    state,
                    "预算币种符号不明确，请使用 SGD、USD、CNY 等三字母代码，或明确说新加坡元、美元、人民币。",
                    "The budget currency symbol is ambiguous. Please use a three-letter code such as SGD, USD, or CNY, or name the currency.",
                ),
            }
        # The saved budget is a monthly rent limit, so a yearly or whole-lease budget is spread out.
        months = state.get("budget_months") or 1
        if currency == "SGD":
            conversion = (
                {"original_amount": amount, "original_currency": "SGD", "amount_sgd": amount, "months": months, "monthly_sgd": amount // months}
                if months > 1
                else None
            )
            return {
                "preferences": state["preferences"].model_copy(
                    update={"max_price_sgd": amount // months}
                ),
                "budget_amount": None,
                "budget_currency": None,
                "budget_months": None,
                "budget_conversion": conversion,
                "budget_conversion_error": None,
            }
        try:
            conversion = convert_to_sgd(amount, currency)
            if months > 1:
                conversion = {**conversion, "months": months, "monthly_sgd": conversion["amount_sgd"] // months}
        except (CurrencyConversionError, ValueError):
            return {
                "budget_conversion_error": "conversion_failed",
                "response_draft": _text(
                    state,
                    f"目前无法将 {currency} 预算换算为 SGD，因此没有使用未经换算的金额搜索。请稍后重试或直接提供 SGD 预算。",
                    f"I could not convert the {currency} budget to SGD, so I did not search using the unconverted amount. Please try again later or provide a budget in SGD.",
                ),
            }
        return {
            "preferences": state["preferences"].model_copy(
                update={"max_price_sgd": conversion.get("monthly_sgd", conversion["amount_sgd"])}
            ),
            "budget_amount": None,
            "budget_currency": None,
            "budget_months": None,
            "budget_conversion": conversion,
            "budget_conversion_error": None,
        }

    def route_after_budget(state: AgentState):
        return "error" if state.get("budget_conversion_error") else "search"

    def prepare_search_node(state: AgentState):
        return {
            "listings": [],
            "pending_listings": [],
            "confirm_listings": [],
            "confirm_check_summary": None,
            "decision_context": [],
            "restrictions": {},
            "ranked_listings": [],
            "listing_check_summary": None,
            "relaxations": [],
            "shown_listing_ids": [],
            "missing_preferences": [],
        }

    def preview_relaxation_node(state: AgentState):
        index = (state.get("relaxation_number") or 1) - 1
        suggestion = state["relaxations"][index]
        preferences = state["preferences"].model_copy(
            update={suggestion["field"]: suggestion["suggested"]}
        )
        listings = search_listings(
            connection,
            preferences,
            _search_exclusions(state),
        )
        restrictions = {
            listing["listing_id"]: extract_restrictions(listing)
            for listing in listings
        }
        validation = validate_ranked_listings(
            connection,
            rank_listings(listings, preferences),
            listing_checker,
            result_limit=3,
        )
        ranked = validation["ranked_listings"]
        response = render_relaxation_preview(
            suggestion,
            ranked,
            restrictions,
            _language(state),
            check_summary=validation["summary"],
        )
        if suggestion["match_count"] != len(ranked):
            response = _text(
                state,
                "本次检查结果已更新，可展示数量与之前的建议不同。\n\n",
                "The check results have changed, so the displayable count differs from the earlier suggestion.\n\n",
            ) + response
        suggestions = list(state["relaxations"])
        suggestions[index] = {
            **suggestion,
            "match_count": len(ranked),
            "check_summary": validation["summary"],
        }
        return {
            "response_draft": response,
            "relaxations": suggestions,
            "shown_listing_ids": _shown_listing_ids(ranked),
        }

    def search_node(state: AgentState):
        # As the agent searches: strict matches, and listings blocked only by data that does not say.
        strict, pending = search_with_unknowns(
            connection,
            state["preferences"],
            _search_exclusions(state),
        )
        return {"listings": strict, "pending_listings": pending}

    def restrictions_node(state: AgentState):
        return {
            "restrictions": {
                listing["listing_id"]: extract_restrictions(listing)
                for listing in state["listings"]
            }
        }

    def rank_node(state: AgentState):
        return {
            "ranked_listings": rank_listings(state["listings"], state["preferences"])
        }

    def validate_listing_status_node(state: AgentState):
        validation = (
            validate_ranked_listings(
                connection,
                state["ranked_listings"],
                listing_checker,
                result_limit=3,
            )
            if state["ranked_listings"]
            else None
        )
        ranked = validation["ranked_listings"] if validation else []
        valid_ids = {item["listing"]["listing_id"] for item in ranked}
        # Fewer strict matches than three are filled with listings to confirm, fewer unstated
        # conditions first and rank order kept within each group, as the agent does.
        pending = state.get("pending_listings", [])
        confirm = (
            validate_ranked_listings(
                connection,
                sorted(
                    rank_listings(pending, state["preferences"]),
                    key=lambda item: len(item["listing"]["unknown_conditions"]),
                ),
                listing_checker,
                result_limit=3 - len(ranked),
            )
            if pending and len(ranked) < 3
            else None
        )
        confirmed = confirm["ranked_listings"] if confirm else []
        return {
            "ranked_listings": ranked,
            "listing_check_summary": validation and validation["summary"],
            "confirm_listings": confirmed,
            "confirm_check_summary": confirm and confirm["summary"],
            "listings": [
                listing
                for listing in state["listings"]
                if listing["listing_id"] in valid_ids
            ],
            "restrictions": {
                item["listing"]["listing_id"]: extract_restrictions(item["listing"])
                for item in [*ranked, *confirmed]
            },
        }

    def diagnose_node(state: AgentState):
        return {
            "decision_context": diagnose_conditions(
                connection,
                state["preferences"],
                _search_exclusions(state),
            )
        }

    def relaxation_node(state: AgentState):
        return {
            "relaxations": analyze_relaxations(
                connection,
                state["preferences"],
                _search_exclusions(state),
                listing_checker,
            )
        }

    def route_after_search(state: AgentState):
        return "matches" if state["listings"] or state.get("pending_listings") else "no_matches"

    def route_after_validation(state: AgentState):
        return "matches" if state["ranked_listings"] else "no_matches"

    def respond_node(state: AgentState):
        ranked = state.get("ranked_listings", [])
        confirm = state.get("confirm_listings", [])
        preferences = state["preferences"]
        language = _language(state)
        missing = _open_preferences(preferences)
        response = results_text(state, ranked, confirm, state.get("relaxations"))
        if not ranked:
            response = "\n\n".join(
                part for part in (response, render_decision_context(state.get("decision_context", []), language)) if part
            )
        conversion = state.get("budget_conversion")
        if conversion:
            response = f"{render_budget_conversion(conversion, _language(state))}\n\n{response}"
        excluded = state.get("last_excluded_listing_ids", [])
        if excluded:
            response = _text(
                state,
                f"已排除房源 {', '.join(excluded)}。\n\n{response}",
                f"Excluded listings {', '.join(excluded)}.\n\n{response}",
            )
        if ranked and missing:
            language = _language(state)
            response += _text(
                state,
                f"\n\n如果想继续缩小范围，可以补充{_REFINEMENT_LABELS[language][missing[0]]}。",
                f"\n\nTo narrow the results, you can add {_REFINEMENT_LABELS[language][missing[0]]}.",
            )
        if (ranked or confirm) and preferences.move_in_date:
            response = _text(
                state,
                f"以下房源满足其他可验证条件，但具体入住日期仍需确认。\n\n{response}\n\n入住日期说明：现有数据不足以确认房源是否接受你的具体入住日期，也无法确认房源届时仍然可租；此 Agent 不能代为联系发布方。",
                f"These listings meet the other verifiable criteria, but the exact move-in date still needs confirmation.\n\n{response}\n\nMove-in date note: the current data cannot confirm that a listing accepts your exact move-in date or will still be available then; this agent cannot contact the publisher for you.",
            )
        footers = []
        if state.get("occupant_note"):
            footers.append(render_occupants(state["occupant_note"], language))
        # Commute criteria measure to the user's faculty; without one they cannot be checked.
        if own_commute_needed(preferences) and not preferences.faculty:
            footers.append(render_no_faculty(language))
        return {
            "response_draft": "\n\n".join([response, *footers]),
            "shown_listing_ids": _shown_listing_ids(ranked) + [item["listing"]["listing_id"] for item in confirm],
            "missing_preferences": missing,
        }

    def results_text(state: AgentState, ranked, confirm, relaxations=None) -> str:
        """Strict matches, or why there are none, then the listings to confirm numbered after them."""
        language = _language(state)
        restrictions = state.get("restrictions")
        if ranked or relaxations or not confirm:
            head = render_response(
                ranked,
                restrictions,
                relaxations,
                language=language,
                check_summary=state.get("listing_check_summary"),
            )
        else:
            # Listings to confirm follow, so this does not say that nothing would help.
            summary = state.get("listing_check_summary")
            head = "\n\n".join(
                part
                for part in (
                    summary and _check_summary_text(summary, language),
                    _text(state, "当前没有可展示的严格匹配房源。", "There are currently no strict matches to display."),
                )
                if part
            )
        tail = render_needs_confirmation(
            confirm,
            restrictions,
            language,
            start=len(ranked[:3]) + 1,
            check_summary=state.get("confirm_check_summary"),
        )
        return "\n\n".join(part for part in (head, tail) if part)

    def conversation_node(state: AgentState):
        ranked = state.get("ranked_listings") or []
        confirm = state.get("confirm_listings") or []
        if state["intent"] == "show_results" and confirm:
            response = results_text(state, ranked, confirm)
        else:
            response = render_intent_response(
                state["intent"],
                ranked,
                state.get("restrictions"),
                state.get("relaxations"),
                _language(state),
                check_summary=state.get("listing_check_summary"),
            )
        update: AgentState = {"response_draft": response}
        if state["intent"] == "show_results" and (ranked or confirm):
            update["shown_listing_ids"] = _shown_listing_ids(ranked) + [item["listing"]["listing_id"] for item in confirm]
        if state["intent"] == "reject_relaxation":
            update["relaxations"] = []
        return update

    def generate_response_node(state: AgentState):
        draft = state["response_draft"]
        if state["intent"] in {
            "shortlist_listing",
            "remove_shortlisted_listing",
            "show_shortlist",
        } or state.get("last_excluded_listing_ids"):
            return {"response": draft}
        try:
            reply = model.invoke(
                [
                    (
                        "system",
                        _RESPONSE_PROMPT.format(
                            language=(
                                "English"
                                if _language(state) == "en"
                                else "Simplified Chinese"
                            )
                        ),
                    ),
                    (
                        "human",
                        _text(
                            state,
                            f"用户本轮消息：{state['message']}\n\n已验证事实草稿：\n{draft}",
                            f"User message: {state['message']}\n\nVerified factual draft:\n{draft}",
                        ),
                    ),
                ]
            )
        except Exception as error:
            trace = [*state.get("trace", []), f"[rewrite] model call failed ({type(error).__name__}) -> verified draft"]
            return {"response": draft, "trace": trace}
        content = getattr(reply, "content", None)
        if not (isinstance(content, str) and content.strip()):
            return {"response": draft}
        # The agent's fact check: listing IDs and money, minute or count figures must come from the
        # draft or the message, with no offer the system cannot keep and in the reply language.
        problems = _reply_problems(content, [state["message"], draft], _language(state))
        if problems:
            trace = [*state.get("trace", []), f"[guard] rewrite rejected ({'; '.join(problems)}) -> verified draft"]
            return {"response": draft, "trace": trace}
        return {"response": content.strip()}

    graph = StateGraph(AgentState)
    graph.add_node("begin_turn", begin_turn_node)
    graph.add_node("interpret", interpret_node)
    graph.add_node("apply_rejections", apply_rejections_node)
    graph.add_node("apply_relaxation", apply_relaxation_node)
    graph.add_node("shortlist", shortlist_node)
    graph.add_node("remove_shortlist", remove_shortlist_node)
    graph.add_node("show_shortlist", show_shortlist_node)
    graph.add_node("compare_shortlist", compare_shortlist_node)
    graph.add_node("show_listing_details", show_listing_details_node)
    graph.add_node("explain_listing", explain_listing_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("normalize_budget", normalize_budget_node)
    graph.add_node("prepare_search", prepare_search_node)
    graph.add_node("preview_relaxation", preview_relaxation_node)
    graph.add_node("search", search_node)
    graph.add_node("restrictions", restrictions_node)
    graph.add_node("rank", rank_node)
    graph.add_node("validate_listing_status", validate_listing_status_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("relaxation", relaxation_node)
    graph.add_node("respond", respond_node)
    graph.add_node("conversation", conversation_node)
    graph.add_node("generate_response", generate_response_node)
    graph.add_edge(START, "begin_turn")
    graph.add_edge("begin_turn", "interpret")
    graph.add_conditional_edges(
        "interpret",
        route_after_interpret,
        {
            "search": "normalize_budget",
            "clarify": "clarification",
            "reject": "apply_rejections",
            "accept": "apply_relaxation",
            "shortlist": "shortlist",
            "remove_shortlist": "remove_shortlist",
            "show_shortlist": "show_shortlist",
            "compare_shortlist": "compare_shortlist",
            "show_listing_details": "show_listing_details",
            "explain_listing": "explain_listing",
            "preview": "preview_relaxation",
            "conversation": "conversation",
        },
    )
    graph.add_edge("apply_rejections", "normalize_budget")
    graph.add_edge("apply_relaxation", "prepare_search")
    graph.add_edge("shortlist", "generate_response")
    graph.add_edge("remove_shortlist", "generate_response")
    graph.add_edge("show_shortlist", "generate_response")
    graph.add_edge("compare_shortlist", "generate_response")
    graph.add_edge("show_listing_details", "generate_response")
    graph.add_edge("explain_listing", "generate_response")
    graph.add_conditional_edges(
        "normalize_budget",
        route_after_budget,
        {"search": "prepare_search", "error": "generate_response"},
    )
    graph.add_edge("prepare_search", "search")
    graph.add_conditional_edges(
        "search",
        route_after_search,
        {"matches": "restrictions", "no_matches": "diagnose"},
    )
    graph.add_edge("restrictions", "rank")
    graph.add_edge("rank", "validate_listing_status")
    graph.add_conditional_edges(
        "validate_listing_status",
        route_after_validation,
        {"matches": "respond", "no_matches": "diagnose"},
    )
    graph.add_edge("diagnose", "relaxation")
    graph.add_edge("relaxation", "respond")
    graph.add_edge("respond", "generate_response")
    graph.add_edge("conversation", "generate_response")
    graph.add_edge("preview_relaxation", "generate_response")
    graph.add_edge("clarification", "generate_response")
    graph.add_edge("generate_response", END)
    return graph.compile(checkpointer=checkpointer)


def _accepts_first(message: str) -> bool:
    return message.casefold().strip(" \t\r\n。！!，,") in _ACCEPT_FIRST


def _asks_to_show_shortlist(message: str) -> bool:
    text = message.casefold()
    shortlist_terms = (
        "候选清单",
        "候选列表",
        "收藏清单",
        "收藏夹",
        "shortlist",
        "saved listings",
    )
    mutation_terms = ("加入", "添加", "放入", "移除", "删除", "不想", "不考虑", "add", "remove")
    return any(term in text for term in shortlist_terms) and not any(
        term in text for term in mutation_terms
    )


def _asks_to_compare_listings(message: str) -> bool:
    text = message.casefold()
    compare_terms = ("比较", "对比", "哪个好", "哪套更好", "compare", "versus", " vs ")
    shortlist_terms = ("候选", "收藏", "shortlist", "saved")
    return any(term in text for term in compare_terms) and (
        len(_listing_ids_in(message)) >= 2
        or any(term in text for term in shortlist_terms)
    )


def _asks_to_explain(message: str) -> bool:
    """Why a listing ranks where it does or where its facts come from (为什么推荐, 价格从哪来)."""
    text = message.casefold()
    return any(term in text for term in ("为什么", "为何", "从哪", "来源", "依据", "why", "where does", "where do", "source"))


def _asks_to_show_listing_details(message: str) -> bool:
    text = message.casefold()
    return any(term in text for term in ("详情", "详细信息", "details")) or any(
        term in text for term in ("查看", "看看", "看下", "view")
    )


def _listing_ids_in(message: str) -> list[str]:
    return list(
        dict.fromkeys(
            re.findall(
                r"(?<![A-Z0-9])(?:S\d+|\d{8,9})(?![A-Z0-9])",
                message.upper(),
            )
        )
    )


def _selected_rejection_ids(state: AgentState) -> list[str]:
    shown = state.get("shown_listing_ids", [])
    numbers = state.get("rejected_listing_numbers", [])
    if state.get("reject_all_shown") or (
        state.get("intent") == "reject_results" and not numbers
    ):
        return shown
    return list(
        dict.fromkeys(
            shown[number - 1]
            for number in numbers
            if 1 <= number <= len(shown)
        )
    )


def _shown_listing_ids(ranked: list[RankingResult]) -> list[str]:
    return [item["listing"]["listing_id"] for item in ranked[:3]]


def _faculty(name: str | None) -> str | None:
    """A recorded faculty's English name, from its English or Chinese name or abbreviation."""
    faculty = find_faculty(name) if name else None
    return faculty and faculty["name"]


def _preferences(state: AgentState) -> SearchPreferences:
    """The saved criteria with the faculty, also before the first search."""
    return (state.get("preferences") or SearchPreferences()).model_copy(update={"faculty": state.get("faculty")})


def _search_exclusions(state: AgentState) -> list[str]:
    return list(
        dict.fromkeys(
            [
                *state.get("excluded_listing_ids", []),
                *state.get("shortlisted_listing_ids", []),
            ]
        )
    )


def _open_preferences(preferences: SearchPreferences) -> list[str]:
    missing = []
    if preferences.max_price_sgd is None:
        missing.append("max_price_sgd")
    # Whole unit or room first: the data states it for almost every listing, room type for about a third.
    if preferences.rental_scope is None and preferences.room_type is None:
        missing.append("rental_scope")
    elif preferences.rental_scope == "room" and preferences.room_type is None and not preferences.room_type_flexible:
        missing.append("room_type")
    if preferences.move_in_date is None and not preferences.move_in_flexible:
        missing.append("move_in_date")
    return missing


def _has_search_criteria(preferences: SearchPreferences) -> bool:
    return any(
        value != SearchPreferences.model_fields[field].default
        for field, value in preferences.model_dump().items()
        if field not in {"room_type_flexible", "move_in_flexible"}
    )


def _response_language(
    message: str,
    previous: ResponseLanguage | None = None,
) -> ResponseLanguage:
    text = message.casefold().strip()
    if any(
        phrase in text
        for phrase in ("用英文", "英文回答", "说英文", "reply in english", "respond in english")
    ):
        return "en"
    if any(
        phrase in text
        for phrase in ("用中文", "中文回答", "说中文", "reply in chinese", "respond in chinese")
    ):
        return "zh"
    if re.search(r"[\u4e00-\u9fff]", message):
        return "zh"

    words = re.findall(r"[a-z]+", text)
    if not words or all(word in {"yes", "no", "ok", "okay"} for word in words):
        return previous or ("en" if words else "zh")
    if all(len(word) == 1 for word in words):
        return previous or "zh"
    return "en"


def _language(state: AgentState) -> ResponseLanguage:
    return state.get("response_language", "zh")


def _text(state: AgentState, zh: str, en: str) -> str:
    return en if _language(state) == "en" else zh


def _reply_problems(reply: str, sources: list[str], language: ResponseLanguage) -> list[str]:
    """Why a reply cannot be shown; listing IDs and money, minute or count figures need a source."""
    source = "\n".join(sources)
    problems = []
    listing_ids = sorted(set(_listing_ids_in(reply)) - set(_listing_ids_in(source)))
    if listing_ids:
        problems.append(f"it names listings that no tool returned: {', '.join(listing_ids)}")
    known = {_number(value) for value in re.findall(_NUMBER, source)}
    figures = sorted({_number(money or other) for money, other in _CLAIMED_NUMBER.findall(reply)} - known)
    if figures:
        problems.append(f"it states figures that no tool returned: {', '.join(figures)}")
    if _UNSUPPORTED_ACTION_OFFER.search(reply) or _UNSUPPORTED_OFFER_EN.search(reply):
        problems.append("it offers an action this agent cannot take")
    if _CYRILLIC.search(reply) or (language == "en" and _HAN.search(reply)) or (language == "zh" and not _HAN.search(reply)):
        problems.append("it is not in the reply language")
    return problems


def _number(text: str) -> str:
    try:
        return format(Decimal(text.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return text
