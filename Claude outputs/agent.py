"""Tool-calling agent: the model chooses tools, code owns facts and state.

graph.py stays as the fixed-workflow baseline (python demo.py --workflow).
"""

import json
import re
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, ValidationError

from decision import (
    active_conditions,
    condition_status,
    diagnose_conditions,
    explain_listing,
    load_source_evidence,
    mrt_minutes,
    search_with_unknowns,
    whole,
)
from exchange import CurrencyConversionError, convert_to_sgd
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
from response import (
    _check_summary_text,
    render_comparison,
    render_decision_context,
    render_listing_details,
    render_listing_explanation,
    render_needs_confirmation,
    render_preference_changes,
    render_response,
)
from tools import (
    check_listing_url,
    extract_restrictions,
    get_listings_by_ids,
    rank_listings,
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
- decision_context counts are database counts before link checks. An active link does not
  prove the room is still available; an unknown link status does not mean the listing is gone.
- You cannot contact landlords or agents, confirm availability, reserve rooms or arrange
  viewings, so never offer to. Only offer what the tools do: search, preview a change, show
  details, explain a ranking, compare, shortlist, exclude or restore listings.

Using tools
- Search as soon as the user gives at least one criterion instead of asking questions first.
  Afterwards you may mention one item from missing_refinements.
- Resolve "the second one" with shown_listings_in_display_order, "this one" with
  last_viewed_listing_id or a single shown listing, and saved listings with the shortlist.
  Ask when a reference is ambiguous.
- Call as many tools as the request needs, for example shortlist one listing and show the
  details of another in the same turn.
- When there are no or few strict matches, use decision_context to explain which condition
  blocks results and whether that is only because the data does not state it. You may preview
  one relaxation, but only the user can accept it.
- Save a preference change only when the latest user message asks for it, and copy the user's
  words that ask for it into user_quote. Use preview=true to look without saving. Never loosen
  a condition on your own.
- Budgets without a currency, including the generic 元, are SGD; 新币 and 新加坡元 are SGD;
  人民币 and RMB are CNY. A bare $ or ¥ is ambiguous, so ask. Pass non-SGD amounts as budget.
- Room types are common_room, master_room, shared_room or studio; district codes look like
  D05. Resolve relative move-in dates from today. Set cooking_required only when cooking is
  required. When the user accepts any room type, clear room_type and set room_type_flexible.
- Present listings in the order and numbering the tools give. Saved preference changes,
  shortlist changes and exclusions are shown to the user automatically, so do not repeat them.
"""

_MOVE_IN_NOTE = (
    "入住日期说明：现有数据不足以确认房源是否接受你的具体入住日期，也无法确认房源届时仍然可租；此 Agent 不能代为联系发布方。",
    "Move-in date note: the current data cannot confirm that a listing accepts your exact move-in date or will still be available then; this agent cannot contact the publisher for you.",
)
_FALLBACK = (
    "抱歉，我没能可靠地回答这个问题。你可以告诉我搜索条件，或者让我查看、比较、收藏某套房源。",
    "Sorry, I could not answer that reliably. You can give me search criteria, or ask me to show, compare or shortlist a listing.",
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
    # Reset at the start of every turn.
    tool_rounds: int
    drafts: list[str]
    notes: list[str]
    observations: list[str]
    trace: list[str]


class Budget(BaseModel):
    amount: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code such as SGD, CNY or USD.")


class SearchArgs(BaseModel):
    """Search with the saved preferences plus optional changes. Returns strict matches, listings that need confirmation because the data does not state some requirement, and decision_context: what dropping each condition alone would yield."""

    set: SearchPreferences = Field(
        default_factory=SearchPreferences,
        description="Only the preference fields to change; null clears a field.",
    )
    budget: Budget | None = Field(None, description="A budget stated in a currency other than SGD.")
    preview: bool = Field(False, description="True to look at results without saving the changes.")
    user_quote: str = Field("", description="The user's words from the latest message that ask for the saved change.")


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
    def validate(ranked, **limits):
        return validate_ranked_listings(connection, ranked, listing_checker, **limits)

    def restrictions_of(ranked):
        return {
            item["listing"]["listing_id"]: extract_restrictions(item["listing"])
            for item in ranked
        }

    def one_listing(listing_id: str):
        listings = get_listings_by_ids(connection, _clean_ids([listing_id]))
        if not listings:
            raise ToolError(f"Listing {listing_id} was not found.")
        return listings[0]

    def search(work, args: SearchArgs):
        current = work["preferences"]
        changes = {
            field: value
            for field, value in args.set.model_dump(exclude_unset=True).items()
            if getattr(current, field) != value
        }
        conversion = None
        if args.budget:
            amount = args.budget.amount
            if args.budget.currency != "SGD":
                try:
                    conversion = convert_to_sgd(amount, args.budget.currency)
                except (CurrencyConversionError, ValueError) as error:
                    raise ToolError(f"{error}. Do not search with the unconverted amount.") from error
                amount = conversion["amount_sgd"]
            if amount != current.max_price_sgd:
                changes["max_price_sgd"] = amount
        if changes and not args.preview and not _quotes(args.user_quote, work["message"]):
            raise ToolError(
                "Saving preference changes needs user_quote copied from the latest user message. "
                "Use preview=true to only look."
            )
        preferences = current.model_copy(update=changes)
        if not _has_search_criteria(preferences):
            raise ToolError("There are no search criteria yet. Ask for one, such as budget, district, room type or MRT walking time.")

        excluded = _search_exclusions(work)
        strict, pending = search_with_unknowns(connection, preferences, excluded)
        strict_check = validate(rank_listings(strict, preferences), result_limit=3)
        shown = strict_check["ranked_listings"]
        pending_check = (
            validate(rank_listings(pending, preferences), result_limit=3 - len(shown))
            if pending and len(shown) < 3
            else None
        )
        pending_shown = pending_check["ranked_listings"] if pending_check else []
        context = diagnose_conditions(connection, preferences, excluded)
        language = work["response_language"]

        if not args.preview and changes:
            work["notes"].append(render_preference_changes(current, changes, language))
            work["preferences"] = preferences
        if conversion:
            (work["drafts"] if args.preview else work["notes"]).append(_conversion_text(work, conversion))
        work["shown_listing_ids"] = [item["listing"]["listing_id"] for item in [*shown, *pending_shown]]

        parts = [_text(work, "预览（尚未修改你的搜索条件）：", "Preview (your saved criteria have not changed):")] if args.preview else []
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
        missing = _open_preferences(preferences)
        if not shown:
            parts.append(render_decision_context(context, language))
        elif missing:
            label = _REFINEMENT_LABELS[language][missing[0]]
            parts.append(_text(work, f"如果想继续缩小范围，可以补充{label}。", f"To narrow the results, you can add {label}."))
        if preferences.move_in_date:
            parts.append(_text(work, *_MOVE_IN_NOTE))
        work["drafts"].append("\n\n".join(part for part in parts if part))

        return {
            "preview": args.preview,
            "preferences": preferences.model_dump(mode="json", exclude_defaults=True),
            "saved_changes": {} if args.preview else changes,
            "budget_conversion": conversion,
            "strict_matches": {
                "database_count": len(strict),
                "check_summary": strict_check["summary"],
                "listings": [_facts(item, position) for position, item in enumerate(shown, 1)],
            },
            "needs_confirmation": {
                "database_count": len(pending),
                "check_summary": pending_check and pending_check["summary"],
                "listings": [
                    _facts(item, position)
                    for position, item in enumerate(pending_shown, len(shown) + 1)
                ],
            },
            "decision_context": context,
            "missing_refinements": missing,
            "move_in_date_cannot_be_verified": preferences.move_in_date is not None,
        }

    def details(work, args: ListingArgs):
        listing = one_listing(args.listing_id)
        listing_id = listing["listing_id"]
        work["viewed_listing_id"] = listing_id
        ranked = validate(rank_listings([listing], work["preferences"]), candidate_limit=1)["ranked_listings"]
        if not ranked:
            work["drafts"].append(_text(work, f"房源 {listing_id} 的原链接已经失效，暂不继续推荐。", f"Listing {listing_id} is no longer available at its original link and will not be recommended."))
            return {"listing_id": listing_id, "link_status": "inactive"}
        listing = ranked[0]["listing"]
        work["drafts"].append(render_listing_details(listing, extract_restrictions(listing), work["response_language"]))
        preferences = work["preferences"]
        return {
            **_facts(ranked[0]),
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
        ranked = validate(rank_listings(listings, work["preferences"]), candidate_limit=len(listings))["ranked_listings"]
        if len(ranked) < 2:
            raise ToolError("At least two existing listings with working links are needed; the shortlist may have fewer.")
        rents = {item["listing"]["listing_id"]: whole(item["listing"]["rent_monthly_sgd"]) for item in ranked}
        minutes = {
            item["listing"]["listing_id"]: mrt_minutes(item["listing"])
            for item in ranked
            if mrt_minutes(item["listing"]) is not None
        }
        work["shown_listing_ids"] = list(rents)
        work["drafts"].append(render_comparison(ranked, restrictions_of(ranked), work["response_language"]))
        return {
            "listings": [_facts(item, position) for position, item in enumerate(ranked, 1)],
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
            for item in validate(rank_listings(listings, work["preferences"]), candidate_limit=len(listings))["ranked_listings"]
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
        return {"shortlist": [_facts(item, position) for position, item in enumerate(ranked, 1)]}

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
        }

    def begin_turn(state: AgentState):
        return {
            "messages": [HumanMessage(content=state["message"])],
            "response_language": _response_language(state["message"], state.get("response_language")),
            "preferences": state.get("preferences") or SearchPreferences(),
            "shown_listing_ids": state.get("shown_listing_ids", []),
            "shortlisted_listing_ids": state.get("shortlisted_listing_ids", []),
            "excluded_listing_ids": state.get("excluded_listing_ids", []),
            "tool_rounds": 0,
            "drafts": [],
            "notes": [],
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
        turn_start = max(index for index, message in enumerate(messages) if isinstance(message, HumanMessage))
        # Earlier turns keep only what the user saw; tool traffic stays in its own turn.
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
                "drafts",
                "notes",
                "observations",
                "trace",
            )
        }
        messages = []
        # Sequential on purpose: later calls in the same message see earlier state changes.
        for call in state["messages"][-1].tool_calls:
            schema, handler = tools.get(call["name"], (None, None))
            try:
                if handler is None:
                    raise ToolError(f"Unknown tool: {call['name']}")
                observation = handler(work, schema.model_validate(call["args"]))
            except (ToolError, ValidationError) as error:
                observation = {"error": str(error)[:600]}
            content = json.dumps(observation, ensure_ascii=False, default=str)
            work["observations"].append(content)
            work["trace"].append(
                f"{call['name']}({json.dumps(call['args'], ensure_ascii=False, default=str)})"
                + (" -> error" if "error" in observation else "")
            )
            messages.append(ToolMessage(content=content, tool_call_id=call["id"], name=call["name"]))
        work.pop("message")
        return {**work, "messages": messages}

    def route_after_agent(state: AgentState):
        last = state["messages"][-1]
        return "tools" if last.tool_calls and state["tool_rounds"] <= max_tool_rounds else "finalize"

    def finalize(state: AgentState):
        last = state["messages"][-1]
        reply = last.content if isinstance(last.content, str) and not last.tool_calls else ""
        sources = [
            state["message"],
            *state["observations"],
            json.dumps(snapshot(state), ensure_ascii=False, default=str),
        ]
        if not reply.strip() or not _grounded(reply, sources) or _off_policy(reply, state["response_language"]):
            reply = "\n\n".join(state["drafts"]) or _text(state, *_FALLBACK)
        response = "\n\n".join([*state["notes"], reply.strip()])
        return {"response": response, "messages": [AIMessage(content=response, id=last.id)]}

    graph = StateGraph(AgentState)
    graph.add_node("begin_turn", begin_turn)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "begin_turn")
    graph.add_edge("begin_turn", "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "finalize": "finalize"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def _tool_spec(name: str, schema: type[BaseModel]) -> dict:
    spec = convert_to_openai_tool(schema)
    spec["function"]["name"] = name
    return spec


def _facts(item: dict, position: int | None = None) -> dict:
    listing = item["listing"]
    facts = {
        "position": position,
        "listing_id": listing["listing_id"],
        "title": listing.get("title"),
        "rent_monthly_sgd": whole(listing.get("rent_monthly_sgd")),
        "room_type": listing.get("room_type"),
        "rental_scope": listing.get("rental_scope"),
        "district_code": listing.get("district_code"),
        "mrt_station": listing.get("mrt_station"),
        "mrt_minutes": mrt_minutes(listing),
        "mrt_from_onemap": listing.get("mrt_walk_minutes") is not None,
        "availability": listing.get("availability_status"),
        "link_status": listing.get("live_status"),
        "link_error": listing.get("live_error_reason"),
        "known_conditions": {
            key: value for key, value in extract_restrictions(listing).items() if value != "unknown"
        },
        "unknown_conditions": listing.get("unknown_conditions"),
        "warnings": item.get("warnings"),
        "rank_value": item.get("rank_value"),
    }
    return {key: value for key, value in facts.items() if value not in (None, [], {})}


def _clean_ids(listing_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip().upper() for value in listing_ids if value.strip()))


def _quotes(quote: str, message: str) -> bool:
    quote, message = (re.sub(r"\W+", "", text.casefold()) for text in (quote, message))
    return bool(quote) and quote in message


def _conversion_text(state, conversion: dict) -> str:
    amount, currency = conversion["original_amount"], conversion["original_currency"]
    rate, sgd, rate_date = conversion["rate_to_sgd"], conversion["amount_sgd"], conversion["rate_date"]
    return _text(
        state,
        f"预算换算：{amount:,} {currency} × {rate} = S${sgd:,}（汇率日期 {rate_date}）。搜索使用 S${sgd:,} 作为月租上限。",
        f"Budget conversion: {amount:,} {currency} × {rate} = S${sgd:,} (rate date {rate_date}). The search used S${sgd:,} as the monthly rent limit.",
    )


def _grounded(reply: str, sources: list[str]) -> bool:
    """Listing IDs and money, minute or count figures in the reply must appear in the sources."""
    source = "\n".join(sources)
    claimed = {_number(money or other) for money, other in _CLAIMED_NUMBER.findall(reply)}
    known = {_number(value) for value in re.findall(_NUMBER, source)}
    return set(_listing_ids_in(reply)) <= set(_listing_ids_in(source)) and claimed <= known


def _number(text: str) -> str:
    try:
        return format(Decimal(text.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return text


def _off_policy(reply: str, language: ResponseLanguage) -> bool:
    return bool(
        _UNSUPPORTED_ACTION_OFFER.search(reply)
        or _UNSUPPORTED_OFFER_EN.search(reply)
        or _CYRILLIC.search(reply)
        or (language == "en" and _HAN.search(reply))
        or (language == "zh" and not _HAN.search(reply))
    )
