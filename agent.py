"""Tool-calling agent: the model chooses tools, code owns facts and state.

graph.py stays as the fixed-workflow baseline (python demo.py --workflow).
"""

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, ValidationError

from decision import (
    active_conditions,
    budget_ladder,
    condition_status,
    default_budget_levels,
    diagnose_conditions,
    explain_listing,
    load_source_evidence,
    mrt_minutes,
    rental_scope_mix,
    search_with_unknowns,
    whole,
)
from exchange import CurrencyConversionError, UnknownCurrencyError, convert_to_sgd
from graph import (
    _CYRILLIC,
    _HAN,
    _REFINEMENT_LABELS,
    _UNSUPPORTED_ACTION_OFFER,
    _has_search_criteria,
    _listing_ids_in,
    _open_preferences,
    _response_language,
    _search_exclusions,
    _text,
)
from models import ResponseLanguage, SearchPreferences
from onemap import OneMapError
from parser import PREFERENCE_GUIDANCE
from response import (
    _availability_text,
    _check_summary_text,
    _link_status_text,
    _render_relaxations,
    render_budget_check,
    render_budget_conversion,
    render_budget_ladder,
    render_comparison,
    render_decision_context,
    render_listing_details,
    render_link_checks,
    render_listing_explanation,
    render_needs_confirmation,
    render_preference_changes,
    render_rental_scope_mix,
    render_response,
    render_saved_preferences,
)
from tools import (
    analyze_relaxations,
    check_listing_url,
    extract_restrictions,
    get_listings_by_ids,
    mrt_distance_m,
    rank_listings,
    location_distance_m,
    rent_percentile_sgd,
    resolve_search_location,
    validate_ranked_listings,
)


MAX_TOOL_ROUNDS = 5
_HISTORY_MESSAGES = 12

_SYSTEM_PROMPT = """You are the Singapore Rental Decision Agent. You help first-time renters in
Singapore, such as students, fresh graduates and new arrivals, find and compare rental listings.
Reply only in {language}, concisely, like a helpful rental adviser. Answer the user's actual
question first and point out the main trade-off when there is one.

Facts
- Every listing fact, price, MRT time, count and link status must come from a tool result in
  this turn or from the conversation state below. Never invent or estimate facts and do not
  calculate new numbers; quote the differences that tools provide.
- "unknown" means the data does not say. Listings under needs_confirmation meet every known
  condition but lack data for some requirements: name those requirements and never call them
  matches.
- decision_context and explore_budgets counts are database counts before link checks.
- A link check and availability are different facts. For every listing you present, give its
  link result from link_note: 链接有效 for an active link; for an unverified link a short
  链接暂时无法确认 is enough because the system appends the full reason at the end. Take
  availability from availability_note. No link result proves a room is still available, and an
  unverified link does not mean the listing is gone.
- You cannot contact landlords or agents, confirm availability, reserve rooms or arrange
  viewings, so never offer to. Only offer what the tools do: search, preview a change, show
  details, explain a ranking, compare, shortlist, exclude or restore listings.

Using tools
- When a tool returns an error that says how to fix the call, fix the arguments and call it
  again before answering. Tell the user about a failure only when the error says to ask them
  or the corrected call fails too.
- Search as soon as the user gives at least one criterion instead of asking questions first.
  Afterwards you may mention one item from missing_refinements.
- Resolve "the second one" with shown_listings_in_display_order, "this one" with
  last_viewed_listing_id or a single shown listing, and saved listings with the shortlist.
  Ask when a reference is ambiguous.
- Call as many tools as the request needs, for example shortlist one listing and show the
  details of another in the same turn.
- When there are no or few strict matches, use decision_context to explain which condition
  blocks results and whether that is only because the data does not state it.
- For a listing under needs_confirmation, name each requirement in its unknown_conditions and
  say the listing does not state it, so the user should ask the publisher; for example, a room
  whose tenant gender rule is not stated may or may not accept them.
- When the user can spend more, is willing to compromise, or asks for better options without
  naming a value, do not ask first and do not save anything. For budget, call explore_budgets;
  for other conditions, preview a search. Say plainly whether the budget is the bottleneck
  (last_saved_search.decision_context shows what dropping each condition yields), name what
  more money improves compared with the weaknesses of the best listing shown so far, then ask
  one question.
- Criteria the user states, including in the first message, are saved: use preview=false and
  copy the user's words that ask for them into user_quote. Use preview=true only for
  hypothetical questions such as 如果预算提高到1500呢. Never loosen a condition on your own.
- When a saved search has no strict matches, the system appends single-condition relaxation
  suggestions with checked counts, so do not repeat them. If the user accepts one, for example
  好 or 接受, save its suggested value with the user's words as user_quote.
- Budgets without a currency, including the generic 元, are SGD; 新币 and 新加坡元 are SGD;
  人民币 and RMB are CNY. A bare $ or ¥ is ambiguous, so ask. Pass non-SGD amounts as budget
  with the ISO 4217 code, for example CNY.
- The saved budget is a monthly rent limit. A budget for a year (一年, 每年, 年预算, per year)
  or a whole lease goes in budget with months set to 12 or the lease length, in any currency
  including SGD; never put such an amount in max_price_sgd. 一年的预算是30万人民币 is
  budget {{"amount": 300000, "currency": "CNY", "months": 12}}.
- 整租 or a whole unit is rental_scope=entire_unit; 合租, 单间 or a room is rental_scope=room.
  Never encode rental scope as room_type. Room types are common_room, master_room, shared_room
  or studio; district codes look like D05.
- Set property_types only when a property type is named: 公寓, condo or private apartment means
  condominium, executive_condominium, apartment and walk_up_apartment; 组屋 or HDB means
  hdb_flat; 有地住宅 or landed means the house types. Property type does not decide rental_scope.
- Resolve relative move-in dates from today. Set cooking_required only when cooking is
  required. When the user accepts any room type, clear room_type and set room_type_flexible.
- In search_listings, put only the fields that change in set; never echo saved or empty fields.
  To drop a saved condition (any district, cooking no longer needed, back to balanced ranking),
  name it in clear. A ranking_priority in set replaces the saved list, so include the saved
  priorities the user keeps, for example ["space", "food_places"] when 也想要餐厅多 follows a
  saved space priority.
- Set tenant_gender only from the user's own words about who will live there: 我是女生 or I am
  female means female, 我是男生 means male, a male-female couple or group means mixed. Never infer
  gender from a name or writing style.
- 不要房东同住 or no live-in owner sets landlord_not_living_in; 要家具 or furnished sets
  furnished_required; 要空调 or aircon sets air_conditioning_required.
- Commute times exist only for public transport to NUS (Kent Ridge campus). 到 NUS 40 分钟以内
  sets max_commute_minutes=40; a short commute to NUS adds commute to ranking_priority.
  For any other destination, say commute times are only available for NUS and set nothing.
- Ranking always weighs MRT walking distance, and rent when there is a budget; the named
  priorities share 70% of the weight. A listing without MRT data or near a station that is not
  open yet counts as a 10-minute walk.
- 空间大一点, 宽敞, a larger room/home or spacious adds space to ranking_priority. This is enough
  to search immediately; do not invent a minimum area, bedroom count or whole-unit preference.
  Set min_area_sqm only for an explicit minimum (平方米/平米/sqm); convert sqft by 0.09290304.
  Space ranks sizes within the same rental_scope and area_scope. Always state which area is
  advertised; floor_reported on a room listing is the whole home's size, not the room's size.
- Present listings in the order and numbering the tools give. Saved preference changes,
  budget conversions and budget_check notes, shortlist changes, exclusions, relaxation
  suggestions and the rental_scope_mix note (whether the shown listings are rooms or whole
  units) are shown to the user automatically, so do not repeat them; you may ask whether the
  user wants a whole unit or a room.
"""
_SYSTEM_PROMPT += PREFERENCE_GUIDANCE

_MOVE_IN_NOTE = (
    "入住日期说明：现有数据不足以确认房源是否接受你的具体入住日期，也无法确认房源届时仍然可租；此 Agent 不能代为联系发布方。",
    "Move-in date note: the current data cannot confirm that a listing accepts your exact move-in date or will still be available then; this agent cannot contact the publisher for you.",
)
_FALLBACK = (
    ("抱歉，我没能可靠地回答这个问题。", "Sorry, I could not answer that reliably."),
    (
        "你可以告诉我新的条件或预算上限，或者让我查看、比较、收藏某套房源。",
        "You can give me new criteria or a budget limit, or ask me to show, compare or shortlist a listing.",
    ),
)
_RETRY = (
    "Your previous reply was not shown to the user because {problems}. Call a tool to get the "
    "facts you need, or answer without them. Reply only in {language}."
)
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


class AgentState(TypedDict, total=False):
    message: str
    response: str
    messages: Annotated[list[AnyMessage], add_messages]
    response_language: ResponseLanguage
    preferences: SearchPreferences
    shown_listing_ids: list[str]
    shortlisted_listing_ids: list[str]
    excluded_listing_ids: list[str]
    viewed_listing_id: str | None
    relaxations: list[dict]
    last_search: dict | None
    # Reset at the start of every turn.
    tool_rounds: int
    drafts: list[str]
    notes: list[str]
    footers: list[str]
    link_checks: list[dict]
    observations: list[str]
    trace: list[str]


class Budget(BaseModel):
    amount: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code such as SGD, CNY or USD.")
    months: int = Field(
        1,
        ge=1,
        le=36,
        description="Months the amount covers: 12 for a yearly budget (一年, 每年, 年预算, per year), the lease length for a whole-lease total, otherwise 1.",
    )


class SearchArgs(BaseModel):
    """Search with the saved preferences plus optional changes. Returns strict matches, listings that need confirmation because the data does not state some requirement, and decision_context: what dropping each condition alone would yield."""

    set: SearchPreferences = Field(
        default_factory=SearchPreferences,
        description="Only the preference fields that change to a new value; leave every other field out. Null or default values here change nothing.",
    )
    clear: list[Literal[tuple(SearchPreferences.model_fields)]] = Field(
        default_factory=list,
        description="Saved preference fields to drop back to 'any', for example district_code when the user no longer minds the district.",
    )
    budget: Budget | None = Field(None, description="A budget in a currency other than SGD, or one covering more than a month in any currency.")
    preview: bool = Field(False, description="True only for hypothetical what-if questions; saved preferences stay unchanged.")
    user_quote: str = Field("", description="The user's words from the latest message that ask for the saved change.")


class BudgetArgs(BaseModel):
    """Compare what different budgets would change while every other saved condition stays: database counts before link checks of strict matches and needs-confirmation listings, how many are within 10 minutes of MRT, and explicit whole units. The last level has no budget limit. Nothing is saved."""

    budgets: list[int] = Field(
        default_factory=list,
        description="Budgets in SGD to compare; leave empty to use about 1.15x, 1.5x and 2.3x the saved budget.",
    )


class ListingArgs(BaseModel):
    """Show one listing's details and how it meets each saved condition."""

    listing_id: str


class ExplainArgs(ListingArgs):
    """Explain why a listing ranks where it does, how each condition is met, and where each fact comes from."""


class CompareArgs(BaseModel):
    """Compare two or more listings with precomputed differences; an empty list compares the shortlist."""

    listing_ids: list[str] = Field(default_factory=list)


class ShortlistArgs(BaseModel):
    """Add or remove shortlisted listings. Call with no arguments to show the shortlist."""

    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class ExcludeArgs(BaseModel):
    """Exclude listings the user rejects from later searches, or restore excluded listings."""

    exclude: list[str] = Field(default_factory=list)
    restore: list[str] = Field(default_factory=list)


class ToolError(ValueError):
    """An expected problem the model should read and act on."""


def build_agent(
    connection: sqlite3.Connection,
    model: Any,
    checkpointer=None,
    listing_checker=check_listing_url,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
):
    # Monthly limits above this barely filter and may be yearly budgets; see search().
    high_rent = rent_percentile_sgd(connection, 0.9)

    def validate(ranked, **limits):
        return validate_ranked_listings(connection, ranked, listing_checker, **limits)

    def checked(work, check):
        """Record the link result of each listing about to be shown, then return those listings."""
        entries = []
        for item in check["ranked_listings"]:
            listing = item["listing"]
            reason = listing.get("live_error_reason")
            work["link_checks"].append(
                {
                    "listing_id": listing["listing_id"],
                    "title": listing.get("title"),
                    "status": listing.get("live_status"),
                    "note": _link_status_text(listing, work["response_language"]),
                }
            )
            entries.append(f"{listing['listing_id']} {listing.get('live_status')}" + (f" ({reason})" if reason else ""))
        if check["summary"]["inactive_count"]:
            entries.append(f"{check['summary']['inactive_count']} inactive skipped")
        if entries:
            work["trace"].append(f"[links] {'; '.join(entries)}")
        return check["ranked_listings"]

    def restrictions_of(ranked):
        return {
            item["listing"]["listing_id"]: extract_restrictions(item["listing"])
            for item in ranked
        }

    def one_listing(listing_id: str):
        listings = get_listings_by_ids(connection, _clean_ids([listing_id]))
        if not listings:
            raise ToolError(
                f"Listing {listing_id} was not found. Use a listing_id from shown_listings_in_display_order "
                "or the shortlist in the conversation state, or ask the user which listing they mean."
            )
        return listings[0]

    def search(work, args: SearchArgs):
        current = work["preferences"]
        defaults = SearchPreferences()
        # Defaults in `set` are ignored: models often echo every field, which would wipe saved
        # criteria. Dropping a criterion goes through `clear`.
        changes = {
            field: value
            for field, value in args.set.model_dump(exclude_unset=True).items()
            if value != getattr(defaults, field) and getattr(current, field) != value
        }
        changes.update(
            {
                field: getattr(defaults, field)
                for field in args.clear
                if getattr(current, field) != getattr(defaults, field)
            }
        )
        conversion = None
        if args.budget:
            amount = args.budget.amount
            if args.budget.currency != "SGD":
                try:
                    conversion = convert_to_sgd(amount, args.budget.currency)
                except UnknownCurrencyError as error:
                    raise ToolError(
                        f"{error}: it is not a currency code the service knows. If the user named a "
                        "currency, call again with its ISO 4217 code (for example CNY for RMB or 人民币); "
                        "if the currency is unclear, ask the user. Do not search with the unconverted amount."
                    ) from error
                except (CurrencyConversionError, ValueError) as error:
                    raise ToolError(
                        f"{error}. The budget cannot be converted right now: tell the user and ask for the "
                        "budget in SGD. Do not search with the unconverted amount."
                    ) from error
                amount = conversion["amount_sgd"]
                work["trace"].append(
                    f"[fx] {conversion['original_amount']} {conversion['original_currency']} -> "
                    f"S${amount} (rate {conversion['rate_to_sgd']}, {conversion['rate_date']})"
                )
            months = args.budget.months
            if months > 1:
                # The saved budget is a monthly rent limit, so a yearly or whole-lease budget is spread out.
                monthly = amount // months
                conversion = {
                    **(conversion or {"original_amount": amount, "original_currency": "SGD", "amount_sgd": amount}),
                    "months": months,
                    "monthly_sgd": monthly,
                }
                work["trace"].append(f"[budget] S${amount} for {months} months -> S${monthly} a month")
                amount = monthly
            if amount != current.max_price_sgd:
                changes["max_price_sgd"] = amount
        # With nothing saved yet there is nothing to preview against, so the first search is saved.
        preview = args.preview and _has_search_criteria(current)
        if changes and not preview and not _quotes(args.user_quote, work["message"]):
            raise ToolError(
                "Saving preference changes needs user_quote copied from the latest user message. "
                "Use preview=true to only look."
            )
        preferences = SearchPreferences.model_validate({**current.model_dump(), **changes})
        try:
            preferences = resolve_search_location(preferences)
        except OneMapError as error:
            raise ToolError(f"Cannot resolve the requested place: {error}. Ask for a more precise address/postcode or user-supplied coordinates; do not invent them.") from error
        changes = {field: getattr(preferences, field) for field in changes}
        if not _has_search_criteria(preferences):
            raise ToolError("There are no search criteria yet. Ask for one, such as budget, district, room type or MRT walking time.")

        excluded = _search_exclusions(work)
        strict, pending = search_with_unknowns(connection, preferences, excluded)
        strict_check = validate(rank_listings(strict, preferences), result_limit=3)
        shown = checked(work, strict_check)
        # Fewer unstated conditions first; rank order is kept within each group.
        pending_ranked = sorted(
            rank_listings(pending, preferences),
            key=lambda item: len(item["listing"]["unknown_conditions"]),
        )
        pending_check = (
            validate(pending_ranked, result_limit=3 - len(shown))
            if pending and len(shown) < 3
            else None
        )
        pending_shown = checked(work, pending_check) if pending_check else []
        context = diagnose_conditions(connection, preferences, excluded)
        language = work["response_language"]
        scope_mix = rental_scope_mix(preferences, strict, [item["listing"] for item in shown])

        relaxations = []
        if not preview:
            if changes:
                work["notes"].append(render_preference_changes(current, changes, language))
                work["preferences"] = preferences
            # Same single-condition policy and URL checks as the workflow's relaxation node.
            if not shown:
                relaxations = analyze_relaxations(connection, preferences, excluded, listing_checker)
            work["relaxations"] = relaxations
            # Without matches to show, say what to relax; with them, whether they are rooms or whole units.
            work["footers"] = (
                [_render_relaxations(relaxations, language)] if not shown
                else [render_rental_scope_mix(scope_mix, language)] if scope_mix
                else []
            )
            work["last_search"] = {
                "strict_database_count": len(strict),
                "needs_confirmation_database_count": len(pending),
                "decision_context": context,
            }
        if conversion:
            (work["drafts"] if preview else work["notes"]).append(render_budget_conversion(conversion, language))
        # A new monthly limit above almost every rent is more likely a yearly or whole-lease budget.
        budget_check = None
        limit = preferences.max_price_sgd
        if "max_price_sgd" in changes and limit and high_rent and limit > high_rent:
            budget_check = {"monthly_limit_sgd": limit, "rent_90th_percentile_sgd": whole(high_rent)}
            (work["drafts"] if preview else work["notes"]).append(render_budget_check(budget_check, language))
        work["shown_listing_ids"] = [item["listing"]["listing_id"] for item in [*shown, *pending_shown]]

        parts = [_text(work, "预览（尚未修改你的搜索条件）：", "Preview (your saved criteria have not changed):")] if preview else []
        if shown:
            parts.append(render_response(shown, restrictions_of(shown), language=language, check_summary=strict_check["summary"]))
        else:
            parts.append(_text(work, "当前没有可展示的完全符合条件的房源。", "There are no listings meeting every condition to display."))
            if strict:
                parts.append(_check_summary_text(strict_check["summary"], language))
        parts.append(
            render_needs_confirmation(
                pending_shown,
                restrictions_of(pending_shown),
                language,
                start=len(shown) + 1,
                check_summary=pending_check and pending_check["summary"],
            )
        )
        # The rental scope note already asks whole unit or room.
        missing = [field for field in _open_preferences(preferences) if not (scope_mix and field == "rental_scope")]
        if not shown:
            parts.append(render_decision_context(context, language))
        elif missing:
            label = _REFINEMENT_LABELS[language][missing[0]]
            parts.append(_text(work, f"如果想继续缩小范围，可以补充{label}。", f"To narrow the results, you can add {label}."))
        if preferences.move_in_date:
            parts.append(_text(work, *_MOVE_IN_NOTE))
        work["drafts"].append("\n\n".join(part for part in parts if part))

        return {
            "preview": preview,
            "preferences": preferences.model_dump(mode="json", exclude_defaults=True),
            "saved_changes": {} if preview else {field: preferences.model_dump(mode="json")[field] for field in changes},
            "budget_conversion": conversion,
            "budget_check": budget_check,
            "strict_matches": {
                "database_count": len(strict),
                "check_summary": strict_check["summary"],
                "listings": [_facts(item, language, position, preferences) for position, item in enumerate(shown, 1)],
            },
            "needs_confirmation": {
                "database_count": len(pending),
                "check_summary": pending_check and pending_check["summary"],
                "listings": [
                    _facts(item, language, position, preferences)
                    for position, item in enumerate(pending_shown, len(shown) + 1)
                ],
            },
            "decision_context": context,
            "rental_scope_mix": scope_mix,
            "relaxation_suggestions": relaxations,
            "missing_refinements": missing,
            "move_in_date_cannot_be_verified": preferences.move_in_date is not None,
        }

    def budgets(work, args: BudgetArgs):
        preferences = work["preferences"]
        saved = preferences.max_price_sgd
        levels = {budget for budget in args.budgets if budget > 0}
        levels = levels or set(default_budget_levels(saved) if saved else [])
        if not levels:
            raise ToolError("There is no saved budget to start from. Pass budgets to compare, or ask the user for a budget.")
        rows = budget_ladder(
            connection,
            preferences,
            [*sorted(levels | ({saved} if saved else set())), None],
            _search_exclusions(work),
        )
        base = rows[0] if saved is None else next(row for row in rows if row["max_price_sgd"] == saved)
        grows = rows[-1]["strict_matches"]["count"] > base["strict_matches"]["count"]
        work["drafts"].append(render_budget_ladder(rows, saved, grows, work["response_language"]))
        return {
            "saved_budget_sgd": saved,
            "counts_are_database_counts_before_link_checks": True,
            "strict_matches_grow_with_budget": grows,
            "levels": rows,
        }

    def details(work, args: ListingArgs):
        listing = one_listing(args.listing_id)
        listing_id = listing["listing_id"]
        work["viewed_listing_id"] = listing_id
        ranked = checked(work, validate(rank_listings([listing], work["preferences"]), candidate_limit=1))
        if not ranked:
            work["drafts"].append(_text(work, f"房源 {listing_id} 的原链接已经失效，暂不继续推荐。", f"Listing {listing_id} is no longer available at its original link and will not be recommended."))
            return {"listing_id": listing_id, "link_status": "inactive"}
        listing = ranked[0]["listing"]
        work["drafts"].append(render_listing_details(listing, extract_restrictions(listing), work["response_language"]))
        preferences = work["preferences"]
        return {
            **_facts(ranked[0], work["response_language"]),
            "bedrooms": listing.get("bedrooms"),
            "bathrooms": listing.get("bathrooms"),
            "area_sqm": listing.get("area_sqm"),
            "max_occupants": listing.get("tenant_count_reported"),
            "address": listing.get("address"),
            "listing_url": listing.get("final_url") or listing.get("listing_url"),
            "conditions": {
                field: condition_status(field, listing, preferences)
                for field in active_conditions(preferences)
            },
        }

    def explain(work, args: ExplainArgs):
        listing = one_listing(args.listing_id)
        listing_id = listing["listing_id"]
        explanation = explain_listing(listing, work["preferences"], load_source_evidence().get(listing_id))
        shown = work["shown_listing_ids"]
        explanation["position_in_shown_listings"] = shown.index(listing_id) + 1 if listing_id in shown else None
        work["viewed_listing_id"] = listing_id
        work["drafts"].append(render_listing_explanation(explanation, work["response_language"]))
        return explanation

    def compare(work, args: CompareArgs):
        listings = get_listings_by_ids(connection, _clean_ids(args.listing_ids) or work["shortlisted_listing_ids"])
        ranked = checked(work, validate(rank_listings(listings, work["preferences"]), candidate_limit=len(listings)))
        if len(ranked) < 2:
            raise ToolError(
                "At least two existing listings with working links are needed; the shortlist may have fewer. "
                "Pass two or more listing_ids from shown_listings_in_display_order, or tell the user the "
                "shortlist has fewer than two listings."
            )
        rents = {item["listing"]["listing_id"]: whole(item["listing"]["rent_monthly_sgd"]) for item in ranked}
        minutes = {
            item["listing"]["listing_id"]: mrt_minutes(item["listing"])
            for item in ranked
            if mrt_minutes(item["listing"]) is not None
        }
        work["shown_listing_ids"] = list(rents)
        work["drafts"].append(render_comparison(ranked, restrictions_of(ranked), work["response_language"]))
        return {
            "listings": [_facts(item, work["response_language"], position) for position, item in enumerate(ranked, 1)],
            "rent_above_cheapest_sgd": {key: rent - min(rents.values()) for key, rent in rents.items()},
            "mrt_minutes_above_closest": {key: value - min(minutes.values()) for key, value in minutes.items()},
        }

    def shortlist(work, args: ShortlistArgs):
        add, remove = _clean_ids(args.add), _clean_ids(args.remove)
        found = [listing["listing_id"] for listing in get_listings_by_ids(connection, add)]
        before = work["shortlisted_listing_ids"]
        work["shortlisted_listing_ids"] = [
            listing_id for listing_id in dict.fromkeys([*before, *found]) if listing_id not in remove
        ]
        work["excluded_listing_ids"] = [
            listing_id for listing_id in work["excluded_listing_ids"] if listing_id not in found
        ]
        saved = work["shortlisted_listing_ids"]
        if add or remove:
            removed = [listing_id for listing_id in remove if listing_id in before]
            not_found = [listing_id for listing_id in add if listing_id not in found]
            # Shown verbatim, like the workflow's shortlist replies, so a wrong pick is visible.
            work["notes"].append(
                _text(
                    work,
                    f"候选清单已更新：加入 {'、'.join(found) or '无'}；移除 {'、'.join(removed) or '无'}；未找到 {'、'.join(not_found) or '无'}。当前候选：{'、'.join(saved) or '空'}。",
                    f"Shortlist updated: added {', '.join(found) or 'none'}; removed {', '.join(removed) or 'none'}; not found {', '.join(not_found) or 'none'}. Current shortlist: {', '.join(saved) or 'empty'}.",
                )
            )
            return {"added": found, "removed": removed, "not_found": not_found, "shortlist": saved}

        listings = get_listings_by_ids(connection, saved)
        by_id = {
            item["listing"]["listing_id"]: item
            for item in checked(work, validate(rank_listings(listings, work["preferences"]), candidate_limit=len(listings)))
        }
        ranked = [by_id[listing_id] for listing_id in saved if listing_id in by_id]
        work["shown_listing_ids"] = [item["listing"]["listing_id"] for item in ranked]
        work["drafts"].append(
            render_response(
                ranked,
                restrictions_of(ranked),
                heading=_text(work, f"候选清单共有 {len(ranked)} 套房源：", f"Your shortlist contains {len(ranked)} listings:"),
                limit=len(ranked),
                language=work["response_language"],
            )
            if ranked
            else _text(work, "候选清单目前是空的。", "Your shortlist is empty.")
        )
        return {"shortlist": [_facts(item, work["response_language"], position) for position, item in enumerate(ranked, 1)]}

    def exclude(work, args: ExcludeArgs):
        excluded, restored = _clean_ids(args.exclude), _clean_ids(args.restore)
        work["excluded_listing_ids"] = [
            listing_id
            for listing_id in dict.fromkeys([*work["excluded_listing_ids"], *excluded])
            if listing_id not in restored
        ]
        work["shortlisted_listing_ids"] = [
            listing_id for listing_id in work["shortlisted_listing_ids"] if listing_id not in excluded
        ]
        if excluded:
            work["notes"].append(_text(work, f"已排除房源 {'、'.join(excluded)}，之后的搜索不再显示（可以说“恢复 {excluded[0]}”撤销）。", f"Excluded listings {', '.join(excluded)} from later searches (say \"restore {excluded[0]}\" to undo)."))
        if restored:
            work["notes"].append(_text(work, f"已恢复房源 {'、'.join(restored)}。", f"Restored listings {', '.join(restored)}."))
        return {"excluded": excluded, "restored": restored, "excluded_listing_ids": work["excluded_listing_ids"]}

    tools = {
        "search_listings": (SearchArgs, search),
        "explore_budgets": (BudgetArgs, budgets),
        "get_listing_details": (ListingArgs, details),
        "explain_listing": (ExplainArgs, explain),
        "compare_listings": (CompareArgs, compare),
        "shortlist": (ShortlistArgs, shortlist),
        "exclude_listings": (ExcludeArgs, exclude),
    }
    bound_model = model.bind_tools([_tool_spec(name, schema) for name, (schema, _) in tools.items()])

    def snapshot(state: AgentState) -> dict:
        preferences = state["preferences"]

        def brief(listing_ids):
            return [
                {
                    "position": position,
                    "listing_id": listing["listing_id"],
                    "title": listing.get("title"),
                    "rent_monthly_sgd": whole(listing.get("rent_monthly_sgd")),
                    "mrt_minutes": mrt_minutes(listing),
                    "district_code": listing.get("district_code"),
                }
                for position, listing in enumerate(get_listings_by_ids(connection, listing_ids), 1)
            ]

        return {
            "today": date.today().isoformat(),
            "saved_preferences": preferences.model_dump(mode="json", exclude_defaults=True),
            "missing_refinements": _open_preferences(preferences),
            "shown_listings_in_display_order": brief(state["shown_listing_ids"]),
            "last_viewed_listing_id": state.get("viewed_listing_id"),
            "shortlist": brief(state["shortlisted_listing_ids"]),
            "excluded_listing_ids": state["excluded_listing_ids"],
            "last_saved_search": state.get("last_search"),
            "pending_relaxations": [
                {key: suggestion[key] for key in ("field", "current", "suggested", "match_count")}
                for suggestion in state["relaxations"]
            ],
        }

    def begin_turn(state: AgentState):
        return {
            "messages": [HumanMessage(content=state["message"])],
            "response_language": _response_language(state["message"], state.get("response_language")),
            "preferences": state.get("preferences") or SearchPreferences(),
            "shown_listing_ids": state.get("shown_listing_ids", []),
            "shortlisted_listing_ids": state.get("shortlisted_listing_ids", []),
            "excluded_listing_ids": state.get("excluded_listing_ids", []),
            "relaxations": state.get("relaxations", []),
            "last_search": state.get("last_search"),
            "tool_rounds": 0,
            "drafts": [],
            "notes": [],
            "footers": [],
            "link_checks": [],
            "observations": [],
            "trace": [],
        }

    def agent_node(state: AgentState):
        language = "English" if state["response_language"] == "en" else "Simplified Chinese"
        system = (
            _SYSTEM_PROMPT.format(language=language)
            + "\nConversation state:\n"
            + json.dumps(snapshot(state), ensure_ascii=False, default=str)
        )
        messages = state["messages"]
        turn_start = _turn_start(messages)
        # Earlier turns keep only what the user saw; tool traffic and retry notes stay in their turn.
        history = [
            message
            for message in messages[:turn_start]
            if isinstance(message, HumanMessage) or (isinstance(message, AIMessage) and not message.tool_calls)
        ]
        try:
            reply = bound_model.invoke([SystemMessage(content=system), *history[-_HISTORY_MESSAGES:], *messages[turn_start:]])
        except Exception:
            if not state["drafts"]:
                raise
            reply = AIMessage(content="")
        return {"messages": [reply], "tool_rounds": state["tool_rounds"] + bool(reply.tool_calls)}

    def tools_node(state: AgentState):
        work = {
            key: list(state[key]) if isinstance(state.get(key), list) else state.get(key)
            for key in (
                "message",
                "response_language",
                "preferences",
                "shown_listing_ids",
                "shortlisted_listing_ids",
                "excluded_listing_ids",
                "viewed_listing_id",
                "relaxations",
                "last_search",
                "drafts",
                "notes",
                "footers",
                "link_checks",
                "observations",
                "trace",
            )
        }
        messages = []
        # Sequential on purpose: later calls in the same message see earlier state changes.
        for call in state["messages"][-1].tool_calls:
            schema, handler = tools.get(call["name"], (None, None))
            line = len(work["trace"])
            work["trace"].append(f"[tool] {call['name']}({json.dumps(call['args'], ensure_ascii=False, default=str)})")
            try:
                if handler is None:
                    raise ToolError(f"Unknown tool: {call['name']}. Use one of: {', '.join(tools)}.")
                observation = handler(work, schema.model_validate(call["args"]))
            except ToolError as error:
                observation = {"error": str(error)[:600]}
            except ValidationError as error:
                observation = {"error": f"The arguments do not match the {call['name']} schema; fix them and call again. {error}"[:600]}
            if "error" in observation:
                work["trace"][line] += f" -> error: {observation['error'][:200]}"
            content = json.dumps(observation, ensure_ascii=False, default=str)
            work["observations"].append(content)
            messages.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        work.pop("message")
        return {**work, "messages": messages}

    def route_after_agent(state: AgentState):
        last = state["messages"][-1]
        return "tools" if last.tool_calls and state["tool_rounds"] <= max_tool_rounds else "finalize"

    def finalize(state: AgentState):
        messages = state["messages"]
        last = messages[-1]
        language = state["response_language"]
        # .text also reads Responses API content blocks and skips reasoning blocks.
        reply = "" if last.tool_calls else last.text
        sources = [
            state["message"],
            *state["observations"],
            json.dumps(snapshot(state), ensure_ascii=False, default=str),
        ]
        problems = _reply_problems(reply, sources, language) if reply.strip() else []
        trace = list(state["trace"])
        retried = any(isinstance(message, SystemMessage) for message in messages[_turn_start(messages):])
        if problems and not retried:
            # One retry: the model sees why its reply was rejected and can fetch real facts.
            trace.append(f"[guard] reply rejected ({'; '.join(problems)}) -> retry")
            feedback = _RETRY.format(
                problems="; ".join(problems),
                language="English" if language == "en" else "Simplified Chinese",
            )
            return {"messages": [RemoveMessage(id=last.id), SystemMessage(content=feedback)], "trace": trace}
        if problems:
            trace.append(f"[guard] reply rejected ({'; '.join(problems)}) -> fallback")
        footers = list(state["footers"])
        if problems or not reply.strip():
            # Drafts already carry each unverified link's reason in their data notes.
            reply = "\n\n".join(state["drafts"]) or fallback(state)
        else:
            latest = {check["listing_id"]: check for check in state["link_checks"]}
            unverified = [check for check in latest.values() if check["status"] == "unknown"]
            if unverified:
                footers.append(render_link_checks(unverified, language))
        response = "\n\n".join([*state["notes"], reply.strip(), *footers])
        return {"response": response, "trace": trace, "messages": [AIMessage(content=response, id=last.id)]}

    def fallback(state: AgentState) -> str:
        language = state["response_language"]
        shown = get_listings_by_ids(connection, state["shown_listing_ids"])
        listings = ("；" if language == "zh" else "; ").join(
            f"{position}. {listing.get('title')} ({listing['listing_id']})"
            for position, listing in enumerate(shown, 1)
        )
        parts = [
            _text(state, *_FALLBACK[0]),
            render_saved_preferences(state["preferences"], language),
            _text(state, f"上次展示的房源：{listings}", f"Last shown listings: {listings}") if shown else "",
            _text(state, *_FALLBACK[1]),
        ]
        return "\n".join(part for part in parts if part)

    def route_after_finalize(state: AgentState):
        return "agent" if isinstance(state["messages"][-1], SystemMessage) else END

    graph = StateGraph(AgentState)
    graph.add_node("begin_turn", begin_turn)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "begin_turn")
    graph.add_edge("begin_turn", "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "finalize": "finalize"})
    graph.add_edge("tools", "agent")
    graph.add_conditional_edges("finalize", route_after_finalize, {"agent": "agent", END: END})
    return graph.compile(checkpointer=checkpointer)


def _tool_spec(name: str, schema: type[BaseModel]) -> dict:
    spec = convert_to_openai_tool(schema)
    spec["function"]["name"] = name
    return spec


def _facts(item: dict, language: ResponseLanguage, position: int | None = None, preferences: SearchPreferences | None = None) -> dict:
    listing = item["listing"]
    facts = {
        "position": position,
        "listing_id": listing["listing_id"],
        "title": listing.get("title"),
        "rent_monthly_sgd": whole(listing.get("rent_monthly_sgd")),
        "room_type": listing.get("room_type"),
        "rental_scope": listing.get("rental_scope"),
        "property_type": listing.get("property_type"),
        "area_sqm": listing.get("area_sqm"),
        "area_scope": listing.get("area_scope"),
        "district_code": listing.get("district_code"),
        "mrt_station": listing.get("mrt_station"),
        "mrt_station_not_open_yet": listing.get("mrt_operation_status") == "under_construction" or None,
        "mrt_minutes": mrt_minutes(listing),
        "mrt_distance_m": whole(mrt_distance_m(listing)),
        "mrt_from_onemap": listing.get("mrt_walk_minutes") is not None,
        "commute_nus_minutes": whole(listing.get("commute_nus_minutes")),
        "availability_note": _availability_text(listing, language),
        "nearby_1km": {
            key: listing[field]
            for key, field in (("fnb", "poi_fnb_1km"), ("hawker_centres", "poi_hawker_1km"), ("healthcare", "poi_healthcare_1km"))
            if listing.get(field) is not None
        },
        "link_status": listing.get("live_status"),
        "link_error": listing.get("live_error_reason"),
        "link_note": _link_status_text(listing, language),
        "known_conditions": {
            key: value for key, value in extract_restrictions(listing).items() if value != "unknown"
        },
        "unknown_conditions": listing.get("unknown_conditions"),
        "warnings": item.get("warnings"),
        "rank_value": item.get("rank_value"),
    }
    facts.update({field: listing.get(field) for field in (
        "bathrooms", "private_bathroom", "pets_policy", "rent_price_type", "address", "street_name", "postcode",
        "latitude", "longitude", "coord_source", "coord_error_m", "listed_date", "gender_preference",
        "pg_school_count", "pg_school_nearest_walk_m", "pg_school_nearest_walk_min", "pg_mrt_count", "pg_mrt_nearest_walk_m",
    )})
    facts["nearby_facility_counts"] = {field: listing.get(field) for field in (
        "poi_fnb_1km", "poi_hawker_1km", "poi_library_1km", "poi_sport_1km", "poi_healthcare_1km", "poi_community_1km",
    ) if listing.get(field) is not None}
    if preferences and preferences.nearby_location:
        distance = location_distance_m(listing, preferences.nearby_location)
        facts["distance_to_reference_m"] = round(distance, 1) if distance is not None else None
    return {key: value for key, value in facts.items() if value not in (None, [], {})}


def _clean_ids(listing_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip().upper() for value in listing_ids if value.strip()))


def _quotes(quote: str, message: str) -> bool:
    quote, message = (re.sub(r"\W+", "", text.casefold()) for text in (quote, message))
    return bool(quote) and quote in message


def _turn_start(messages: list[AnyMessage]) -> int:
    return max(index for index, message in enumerate(messages) if isinstance(message, HumanMessage))


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
