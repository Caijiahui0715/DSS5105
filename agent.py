"""Tool-calling agent: the model chooses tools, code owns facts and state.

graph.py stays as the fixed-workflow baseline (python demo.py --workflow).
"""

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
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
from langgraph.config import get_stream_writer
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
from faculties import FACULTIES, find_faculty
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
from profiles import UserProfiles
from response import (
    _availability_text,
    _check_summary_text,
    _link_status_text,
    _render_relaxations,
    render_budget_check,
    render_budget_conversion,
    render_budget_ladder,
    render_commutes,
    render_comparison,
    render_decision_context,
    render_faculty_change,
    render_listing_details,
    render_link_checks,
    render_listing_explanation,
    render_needs_confirmation,
    render_no_faculty,
    render_preference_changes,
    render_remembered_profile,
    render_rental_scope_mix,
    render_response,
    render_saved_preferences,
    TOOL_LABELS,
)
from tools import (
    analyze_relaxations,
    check_listing_url,
    commute,
    commute_minutes,
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
- Commute times are minutes from each listing to the user's NUS faculty (faculty in the
  conversation state): public transport leaving 08:30 on a weekday, or walking when the faculty
  is within 1.5 km and that is faster; the tools say which. 到学校/学院/NUS 40 分钟以内 sets
  max_commute_minutes=40; a short commute adds commute to ranking_priority. For a destination
  that is not an NUS faculty, say commute times only cover NUS faculties and set nothing.
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
# Listed from faculties.py, so the prompt stays in step with the recorded addresses.
_FACULTY_LIST = "; ".join(f"{faculty['name']} ({faculty['campus']})" for faculty in FACULTIES)
_SYSTEM_PROMPT += f"""
NUS faculties and schools
- These have recorded addresses: {_FACULTY_LIST}.
- When the user names one as a place (离 SoC 2 公里内), also in Chinese or as an abbreviation, put
  its English name from this list in nearby_location.query; the system locates it without a
  lookup. Being close still needs an explicit radius, as for any place.
"""
_FACULTY_GUIDANCE = """
The user's faculty (faculty tool)
- faculty in the conversation state is the faculty saved in the user's account, used for every
  commute time in every conversation; null means not set.
- When it is null and the user asks how long a commute takes or states a commute condition, ask
  which NUS faculty they study at and say it will be saved to their account. Their answer is
  enough: call faculty with action=set, the faculty and their words as user_quote.
- When a faculty is saved and the user says they study at a different one, do not change it yet:
  ask 要把你的学院改成X吗？之后所有对话都会按X计算通勤时间。 and call action=set only after they
  agree, quoting their agreement. The system confirms the change to the user.
- For how long listings take to school, call faculty with action=commute. A hypothetical or
  another faculty (如果我在法学院呢) uses action=commute with that faculty and saves nothing.
- Without commute data for a listing, say so and give the straight-line distance and MRT walk the
  tool returns. Never estimate minutes.
"""
_MEMORY_GUIDANCE = """
Long-term memory (user_memory tool)
- memory_consent says whether this user agreed to be remembered across conversations; null means
  not decided. The system asks once after criteria are saved. When the user agrees (记住, 好的记住吧,
  yes remember them) call user_memory with action=allow; when they refuse (不用记, no) action=decline.
- remembered_profile holds criteria this user agreed to keep in an earlier conversation, with the
  user's words behind each field. The system has already shown it; it may be outdated and is not
  applied. When the user wants to reuse it (沿用, 跟上次一样, same as last time) call user_memory with
  action=restore, then search_listings with only the changes the user asks for now.
- 你记得我什么 or what do you remember calls action=show; 忘掉我的信息, 删除我的数据 or forget me calls
  action=forget. Never claim to remember anything that is not in user_memory results or the state.
"""
_MEMORY_ASK = (
    "要我记住这些条件吗？记住后，下次开新对话时我会先问你是否沿用；随时可以说“忘掉我的信息”删除。",
    "Should I remember these criteria? Next time you start a new conversation I will ask whether to reuse them; say \"forget my data\" at any time to delete them.",
)

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
    # ISO date of the latest turn; a later date means the conversation resumed on another day.
    last_active_date: str | None
    # Long-term memory, used only with a profile store: who is talking, the user's words and date
    # behind each saved field, the budget as stated, a profile kept from an earlier conversation
    # that is offered but not applied yet, and whether the system already asked for consent.
    user_id: str | None
    preference_sources: dict
    budget_statement: dict | None
    remembered_profile: dict | None
    memory_asked: bool
    # Each final reply's trace by message id, so the processing steps can be shown again later.
    reply_traces: dict
    # Reset at the start of every turn.
    memory_dirty: bool
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
    clear: list[Literal[tuple(field for field in SearchPreferences.model_fields if field != "faculty")]] = Field(
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


class MemoryArgs(BaseModel):
    """This user's criteria kept across conversations: allow or decline keeping them, show what is kept, forget it, or restore it into this conversation. Act only on the user's own request."""

    action: Literal["allow", "decline", "show", "forget", "restore"]
    user_quote: str = Field("", description="The user's words from the latest message that ask for this; not needed for show.")


class FacultyArgs(BaseModel):
    """The user's NUS faculty, used for every commute time: save it to their account (set), or look up commute times from listings to it or to any other faculty without saving anything (commute)."""

    action: Literal["set", "commute"]
    faculty: str | None = Field(None, description="A recorded faculty by its English name from the list; for commute, leave empty to use the user's saved faculty.")
    listing_ids: list[str] = Field(default_factory=list, description="For commute: the listings to look up; empty means the listings shown last.")
    user_quote: str = Field("", description="For set: the user's words in the latest message that state or confirm the faculty.")


class ToolError(ValueError):
    """An expected problem the model should read and act on."""


def build_agent(
    connection: sqlite3.Connection,
    model: Any,
    checkpointer=None,
    listing_checker=check_listing_url,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    profiles: UserProfiles | None = None,
):
    """With profiles, a user_id in the input enables long-term memory for that user."""
    # Monthly limits above this barely filter and may be yearly budgets; see search().
    high_rent = rent_percentile_sgd(connection, 0.9)
    lowest_rent = rent_percentile_sgd(connection, 0)

    def validate(ranked, **limits):
        checked_links = 0

        def checker(listing_id, url):
            nonlocal checked_links
            checked_links += 1
            _progress(f"正在检查房源链接（第 {checked_links} 套）", f"Checking listing links ({checked_links})")
            return listing_checker(listing_id, url)

        return validate_ranked_listings(connection, ranked, checker, **limits)

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
                    _progress("正在换算汇率", "Converting the currency")
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
        # A budget missing 万 or 千 is at least ten times too small. A limit under a tenth of the
        # cheapest rent is neither used nor kept, and the system says so itself instead of leaving
        # it to the model; budgets that are only a little low still get relaxation suggestions.
        budget_check = None
        limit = changes.get("max_price_sgd")
        if limit is not None and lowest_rent and limit < lowest_rent / 10:
            del changes["max_price_sgd"]
            budget_check = {
                "monthly_limit_sgd": limit,
                "lowest_rent_sgd": whole(lowest_rent),
                "stated_budget": args.budget and args.budget.model_dump(),
            }
            # The stated budget is not kept either, and there is no conversion to show.
            conversion, args = None, args.model_copy(update={"budget": None})
            note = render_budget_check(budget_check, work["response_language"])
            if note not in work["notes"]:
                work["notes"].append(note)
        # The faculty is not one of the criteria (model_dump leaves it out), so it is carried over.
        preferences = SearchPreferences.model_validate({**current.model_dump(), **changes, "faculty": current.faculty})
        try:
            preferences = resolve_search_location(preferences)
        except OneMapError as error:
            raise ToolError(f"Cannot resolve the requested place: {error}. Ask for a more precise address/postcode or user-supplied coordinates; do not invent them.") from error
        changes = {field: getattr(preferences, field) for field in changes}
        if not _has_search_criteria(preferences):
            raise ToolError(
                "The budget was not used: the system already told the user it is far below every rent and "
                "asked for the correct amount, so do not repeat that; wait for their answer."
                if budget_check
                else "There are no search criteria yet. Ask for one, such as budget, district, room type or MRT walking time."
            )

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
                # The user's words behind each saved field, kept with the profile if they agree.
                sources = dict(work["preference_sources"])
                for field in changes:
                    if getattr(preferences, field) == getattr(defaults, field):
                        sources.pop(field, None)
                    else:
                        sources[field] = {"quote": args.user_quote, "date": date.today().isoformat()}
                work["preference_sources"] = sources
                # Keep the budget as stated so a reused one is converted at that day's rate.
                if args.budget:
                    work["budget_statement"] = args.budget.model_dump()
                elif "max_price_sgd" in changes:
                    work["budget_statement"] = None
                # New criteria supersede what an earlier conversation kept.
                work["remembered_profile"] = None
                work["memory_dirty"] = True
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
            # Ask once whether to keep the saved criteria for later conversations.
            user_id = work.get("user_id")
            if changes and profiles and user_id and not work["memory_asked"] and profiles.consent(user_id) is None:
                work["footers"].append(_text(work, *_MEMORY_ASK))
                work["memory_asked"] = True
            # Commute criteria measure to the user's faculty; without one they cannot be checked.
            commute_asked = preferences.max_commute_minutes is not None or "commute" in preferences.ranking_priority
            if profiles and user_id and commute_asked and not preferences.faculty:
                work["footers"].append(render_no_faculty(language))
            work["last_search"] = {
                "strict_database_count": len(strict),
                "needs_confirmation_database_count": len(pending),
                "decision_context": context,
            }
        if conversion:
            (work["drafts"] if preview else work["notes"]).append(render_budget_conversion(conversion, language))
        # A new monthly limit above almost every rent is more likely a yearly or whole-lease budget.
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
        work["drafts"].append(render_listing_details(listing, extract_restrictions(listing), work["response_language"], ranked[0]["commute"]))
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
            work["memory_dirty"] = True
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
        work["memory_dirty"] = work["memory_dirty"] or bool(excluded or restored)
        if excluded:
            work["notes"].append(_text(work, f"已排除房源 {'、'.join(excluded)}，之后的搜索不再显示（可以说“恢复 {excluded[0]}”撤销）。", f"Excluded listings {', '.join(excluded)} from later searches (say \"restore {excluded[0]}\" to undo)."))
        if restored:
            work["notes"].append(_text(work, f"已恢复房源 {'、'.join(restored)}。", f"Restored listings {', '.join(restored)}."))
        return {"excluded": excluded, "restored": restored, "excluded_listing_ids": work["excluded_listing_ids"]}

    def user_memory(work, args: MemoryArgs):
        user_id = work.get("user_id")
        if not user_id:
            raise ToolError("This conversation has no user id, so nothing can be kept across conversations; tell the user.")
        if args.action != "show" and not _quotes(args.user_quote, work["message"]):
            raise ToolError("This action needs user_quote copied from the latest user message.")
        language = work["response_language"]
        if args.action == "show":
            kept = profiles.profile(user_id)
            work["drafts"].append(
                render_remembered_profile(kept, language, welcome=False) if kept
                else _text(work, "目前没有为你长期保存任何内容。", "Nothing is kept for you across conversations.")
            )
            return {"memory_consent": profiles.consent(user_id), "kept_profile": kept}
        if args.action == "allow":
            profiles.set_consent(user_id, True)
            profiles.save(user_id, _kept_profile(work))
            work["memory_asked"] = True
            work["notes"].append(_text(
                work,
                "好的，已记住当前的条件、候选和排除。下次开新对话时我会先问你是否沿用；随时可以说“忘掉我的信息”删除。",
                "Done: your current criteria, shortlist and exclusions are kept. Next time you start a new conversation I will ask whether to reuse them; say \"forget my data\" at any time to delete them.",
            ))
            return {"memory_consent": True}
        if args.action in ("decline", "forget"):
            profiles.set_consent(user_id, False)
            work["memory_asked"] = True
            work["remembered_profile"] = None
            work["notes"].append(
                _text(work, "好的，不会保存你的条件，新对话不会带入这些内容。", "OK, your criteria will not be kept for new conversations.")
                if args.action == "decline"
                else _text(
                    work,
                    "已删除为你长期保存的条件、候选和排除，之后也不会再保存。当前这段对话的记录仍在，开新对话后不会带入。",
                    "Deleted the criteria, shortlist and exclusions kept for you, and nothing more will be kept. This conversation's own record remains; new conversations will not include it.",
                )
            )
            return {"memory_consent": False, "deleted": args.action == "forget"}

        kept = profiles.profile(user_id)
        if not kept:
            raise ToolError("Nothing is kept for this user; tell the user and ask for their criteria.")
        current = work["preferences"]
        restored = SearchPreferences.model_validate({**kept.get("preferences", {}), "faculty": current.faculty})
        budget, conversion = kept.get("budget"), None
        if budget:
            # Work the monthly limit out again at today's rate; keep the saved one if that fails.
            amount = budget["amount"]
            try:
                if budget["currency"] != "SGD":
                    _progress("正在换算汇率", "Converting the currency")
                    conversion = convert_to_sgd(amount, budget["currency"])
                    amount = conversion["amount_sgd"]
                months = budget.get("months", 1)
                if months > 1:
                    conversion = {
                        **(conversion or {"original_amount": amount, "original_currency": "SGD", "amount_sgd": amount}),
                        "months": months,
                        "monthly_sgd": amount // months,
                    }
                    amount //= months
                restored = restored.model_copy(update={"max_price_sgd": amount})
            except (CurrencyConversionError, ValueError):
                work["notes"].append(_text(
                    work,
                    f"汇率服务暂时不可用，先沿用上次换算的月租上限 S${restored.max_price_sgd:,}。",
                    f"The exchange-rate service is unavailable, so the monthly limit from last time, S${restored.max_price_sgd:,}, is used.",
                ))
        changes = {
            field: getattr(restored, field)
            for field in SearchPreferences.model_fields
            if getattr(restored, field) != getattr(current, field)
        }
        kept_ids = kept.get("shortlisted_listing_ids", [])
        present = [listing["listing_id"] for listing in get_listings_by_ids(connection, kept_ids)]
        gone = [listing_id for listing_id in kept_ids if listing_id not in present]
        work["preferences"] = restored
        work["shortlisted_listing_ids"] = list(dict.fromkeys([*work["shortlisted_listing_ids"], *present]))
        work["excluded_listing_ids"] = list(dict.fromkeys([*work["excluded_listing_ids"], *kept.get("excluded_listing_ids", [])]))
        work["preference_sources"] = kept.get("sources", {})
        work["budget_statement"] = budget
        work["remembered_profile"] = None
        work["relaxations"], work["last_search"] = [], None
        work["memory_dirty"] = True
        if changes:
            work["notes"].append(render_preference_changes(current, changes, language))
        if conversion:
            work["notes"].append(render_budget_conversion(conversion, language))
        work["notes"].append(_text(
            work,
            f"已沿用上次的候选清单：{'、'.join(present) or '空'}" + (f"；{'、'.join(gone)} 已不在当前房源数据中，未恢复。" if gone else "。"),
            f"Restored last time's shortlist: {', '.join(present) or 'empty'}" + (f"; {', '.join(gone)} no longer in the listing data and not restored." if gone else "."),
        ))
        return {
            "restored_preferences": restored.model_dump(mode="json", exclude_defaults=True),
            "budget_conversion": conversion,
            "shortlist": work["shortlisted_listing_ids"],
            "not_restored_delisted": gone,
            "next_step": "Call search_listings with only the changes the user asks for now to show listings.",
        }

    def faculty_tool(work, args: FacultyArgs):
        named = find_faculty(args.faculty) if args.faculty else None
        if args.faculty and not named:
            raise ToolError(
                f"{args.faculty!r} is not a recorded faculty. Use an English name from the NUS faculties list "
                "in your instructions; if the user's faculty is not there, tell the user commute times only cover those."
            )
        saved = work["preferences"].faculty
        if args.action == "set":
            user_id = work.get("user_id")
            if not user_id:
                raise ToolError("This conversation has no user id, so the faculty cannot be saved; tell the user.")
            if not named:
                raise ToolError("Name the faculty to save in faculty.")
            if not _quotes(args.user_quote, work["message"]):
                raise ToolError("Saving the faculty needs user_quote copied from the latest user message that states or confirms it.")
            if named["name"] != saved:
                profiles.set_faculty(user_id, named["name"])
                work["preferences"] = work["preferences"].model_copy(update={"faculty": named["name"]})
                work["notes"].append(render_faculty_change(saved, named["name"], work["response_language"]))
            return {"faculty": named["name"], "campus": named["campus"], "changed": named["name"] != saved}

        faculty = named or find_faculty(saved or "")
        if not faculty:
            raise ToolError("No faculty is saved for this user. Ask which NUS faculty they study at; it will be saved to their account.")
        listing_ids = _clean_ids(args.listing_ids) or work["shown_listing_ids"]
        if not listing_ids and work.get("viewed_listing_id"):
            listing_ids = [work["viewed_listing_id"]]
        listings = get_listings_by_ids(connection, listing_ids)
        if not listings:
            raise ToolError("Name the listings in listing_ids, from shown_listings_in_display_order or the shortlist.")
        to_faculty = SearchPreferences(faculty=faculty["name"])
        place = SimpleNamespace(latitude=faculty["latitude"], longitude=faculty["longitude"])
        rows = [
            {
                "listing_id": listing["listing_id"],
                "title": listing.get("title"),
                "commute_minutes": whole(commute_minutes(listing, to_faculty)),
                "commute_mode": (commute(listing, faculty["name"]) or {}).get("mode"),
                "distance_m": round(distance) if (distance := location_distance_m(listing, place)) is not None else None,
                "mrt_minutes": mrt_minutes(listing),
            }
            for listing in listings
        ]
        work["drafts"].append(render_commutes(faculty["name"], rows, work["response_language"]))
        return {
            "faculty": faculty["name"],
            "campus": faculty["campus"],
            "saved_faculty": saved,
            "trip": "public transport leaving 08:30 on a weekday, or walking within 1.5 km when faster (commute_mode)",
            "listings": rows,
        }

    tools = {
        "search_listings": (SearchArgs, search),
        "explore_budgets": (BudgetArgs, budgets),
        "get_listing_details": (ListingArgs, details),
        "explain_listing": (ExplainArgs, explain),
        "compare_listings": (CompareArgs, compare),
        "shortlist": (ShortlistArgs, shortlist),
        "exclude_listings": (ExcludeArgs, exclude),
    }
    if profiles:
        tools["user_memory"] = (MemoryArgs, user_memory)
        tools["faculty"] = (FacultyArgs, faculty_tool)
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

        memory = (
            {
                "memory_consent": profiles.consent(state["user_id"]),
                "remembered_profile": state.get("remembered_profile"),
                "faculty": preferences.faculty,
            }
            if profiles and state.get("user_id")
            else {}
        )
        return {
            **memory,
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
        language = _response_language(state["message"], state.get("response_language"))
        turn = {"response_language": language}
        preferences = state.get("preferences") or SearchPreferences()
        # The faculty is an account setting that can change between turns, on the web page too.
        user_id = state.get("user_id")
        preferences = preferences.model_copy(update={"faculty": profiles.faculty(user_id) if profiles and user_id else None})
        today = date.today()
        notes, trace = [], []
        # A saved conversation can outlive a data refresh that delisted shortlisted listings.
        shortlisted = state.get("shortlisted_listing_ids", [])
        known = {listing["listing_id"] for listing in get_listings_by_ids(connection, shortlisted)}
        gone = [listing_id for listing_id in shortlisted if listing_id not in known]
        if gone:
            notes.append(_text(
                turn,
                f"候选清单里的 {'、'.join(gone)} 已不在当前房源数据中（可能已下架），已从候选清单移除。",
                f"{', '.join(gone)} from your shortlist no longer appear in the listing data (possibly delisted) and were removed.",
            ))
            trace.append(f"[resume] dropped delisted shortlist entries: {', '.join(gone)}")
        # On a later day, earlier suggestions and counts rest on old data and link checks.
        last_active = state.get("last_active_date")
        new_day = last_active is not None and last_active != today.isoformat()
        if new_day:
            trace.append(f"[resume] last active {last_active}; cleared pending relaxations and last search counts")
            if preferences.move_in_date and preferences.move_in_date < today:
                notes.append(_text(
                    turn,
                    f"你之前填写的入住日期 {preferences.move_in_date.isoformat()} 已经过去，如需更新请告诉我。",
                    f"The move-in date you gave, {preferences.move_in_date.isoformat()}, has passed; tell me if it changed.",
                ))
        # A new conversation of a user who agreed to be remembered opens with what was kept.
        remembered = state.get("remembered_profile")
        if profiles and user_id and not state.get("messages"):
            remembered = profiles.profile(user_id)
            if remembered:
                kept = remembered.get("shortlisted_listing_ids", [])
                present = {listing["listing_id"] for listing in get_listings_by_ids(connection, kept)}
                notes.append(render_remembered_profile(remembered, language, gone=[i for i in kept if i not in present]))
                trace.append(f"[memory] offered the profile kept on {remembered.get('saved_on')}")
        return {
            "messages": [HumanMessage(content=state["message"])],
            "response_language": language,
            "preferences": preferences,
            "shown_listing_ids": state.get("shown_listing_ids", []),
            "shortlisted_listing_ids": [listing_id for listing_id in shortlisted if listing_id in known],
            "excluded_listing_ids": state.get("excluded_listing_ids", []),
            "relaxations": [] if new_day else state.get("relaxations", []),
            "last_search": None if new_day else state.get("last_search"),
            "last_active_date": today.isoformat(),
            "preference_sources": state.get("preference_sources", {}),
            "budget_statement": state.get("budget_statement"),
            "remembered_profile": remembered,
            "memory_asked": state.get("memory_asked", False),
            "memory_dirty": False,
            "tool_rounds": 0,
            "drafts": [],
            "notes": notes,
            "footers": [],
            "link_checks": [],
            "observations": [],
            "trace": trace,
        }

    def agent_node(state: AgentState):
        last = state["messages"][-1]
        _progress(
            *("回复未通过事实核对，正在重写", "Rewriting a reply that failed the fact check") if isinstance(last, SystemMessage)
            else ("正在整理结果", "Putting the results together") if isinstance(last, ToolMessage)
            else ("正在理解你的需求", "Understanding your request")
        )
        language = "English" if state["response_language"] == "en" else "Simplified Chinese"
        system = (
            _SYSTEM_PROMPT.format(language=language)
            + (_MEMORY_GUIDANCE + _FACULTY_GUIDANCE if profiles and state.get("user_id") else "")
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
                "user_id",
                "preference_sources",
                "budget_statement",
                "remembered_profile",
                "memory_asked",
                "memory_dirty",
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
            label = TOOL_LABELS.get(call["name"], (call["name"], call["name"]))
            _progress(f"正在{label[0]}", label[1])
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
        _progress("正在核对回复", "Checking the reply")
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
        # Keep this turn's changes for later conversations, only with consent. While an earlier
        # profile is offered but not reused or replaced, it is left as it was.
        user_id = state.get("user_id")
        if profiles and user_id and state.get("memory_dirty") and not state.get("remembered_profile"):
            if profiles.save(user_id, _kept_profile(state)):
                trace.append("[memory] kept this conversation's criteria for later conversations")
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
        return {
            "response": response,
            "trace": trace,
            "messages": [AIMessage(content=response, id=last.id)],
            "reply_traces": {**(state.get("reply_traces") or {}), last.id: trace},
        }

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


def _progress(zh: str, en: str) -> None:
    """Tell a streaming caller, such as the web server, what is happening; nothing otherwise."""
    try:
        get_stream_writer()({"progress": {"zh": zh, "en": en}})
    except RuntimeError:
        pass  # Outside a graph run.


def _kept_profile(state) -> dict:
    """What long-term memory keeps: saved criteria with their sources, never conversation text."""
    return {
        "preferences": state["preferences"].model_dump(mode="json", exclude_defaults=True),
        "budget": state.get("budget_statement"),
        "sources": state.get("preference_sources") or {},
        "shortlisted_listing_ids": state.get("shortlisted_listing_ids", []),
        "excluded_listing_ids": state.get("excluded_listing_ids", []),
        "response_language": state.get("response_language"),
        "saved_on": date.today().isoformat(),
    }


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
        "commute_minutes_to_faculty": whole((item.get("commute") or {}).get("minutes")),
        "commute_mode": (item.get("commute") or {}).get("mode"),
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
