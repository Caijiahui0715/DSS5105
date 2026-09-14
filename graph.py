import re
import sqlite3
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from models import (
    Listing,
    RankingResult,
    RelaxationSuggestion,
    RestrictionSummary,
    SearchPreferences,
    UserIntent,
)
from parser import parse_turn
from response import render_intent_response, render_relaxation_preview, render_response
from tools import (
    analyze_relaxations,
    extract_restrictions,
    get_listings_by_ids,
    rank_listings,
    search_listings,
)


class AgentState(TypedDict, total=False):
    message: str
    intent: UserIntent
    relaxation_number: int | None
    reject_all_shown: bool
    rejected_listing_numbers: list[int]
    shortlist_listing_numbers: list[int]
    shortlist_listing_ids: list[str]
    shortlisted_listing_number: int | None
    preferences: SearchPreferences
    listings: list[Listing]
    restrictions: dict[str, RestrictionSummary]
    ranked_listings: list[RankingResult]
    relaxations: list[RelaxationSuggestion]
    shown_listing_ids: list[str]
    excluded_listing_ids: list[str]
    shortlisted_listing_ids: list[str]
    last_excluded_listing_ids: list[str]
    missing_preferences: list[str]
    response_draft: str
    response: str


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

_RESPONSE_PROMPT = """Reply in natural, concise Chinese like a helpful rental adviser,
not a form or database dump. The verified draft is the only source of truth. Do not
copy its stock opening or field labels mechanically: answer the user's intent directly
and, when listings exist, briefly point out useful trade-offs already visible in the
draft before presenting the facts in an easy-to-scan form. Preserve every listing ID,
price, MRT value, ranking order, restriction, warning, and whether a relaxation is
only a preview. Do not invent or change listings, facts, availability, amenities, or
user choices. End with at most one short, relevant follow-up question. Return only the
user-facing reply.
"""

_REFINEMENT_LABELS = {
    "max_price_sgd": "每月最高预算",
    "room_type": "房型（例如 Common Room、Master Room 或 Shared Room）",
    "move_in_date": "计划入住时间",
}


def build_graph(connection: sqlite3.Connection, model: Any, checkpointer=None):
    def interpret_node(state: AgentState):
        previous = state.get("preferences")
        relaxations = state.get("relaxations", [])
        if _asks_to_show_shortlist(state["message"]):
            return {
                "intent": "show_shortlist",
                "relaxation_number": None,
                "reject_all_shown": False,
                "rejected_listing_numbers": [],
                "shortlist_listing_numbers": [],
                "shortlist_listing_ids": [],
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
        )
        return {
            "intent": turn.intent,
            "relaxation_number": turn.relaxation_number,
            "reject_all_shown": turn.reject_all_shown,
            "rejected_listing_numbers": turn.rejected_listing_numbers,
            "shortlist_listing_numbers": turn.shortlist_listing_numbers,
            "shortlist_listing_ids": (
                _listing_ids_in(state["message"]) or turn.shortlist_listing_ids
            ),
            "shortlisted_listing_number": turn.shortlisted_listing_number,
            "last_excluded_listing_ids": [],
            "preferences": turn.preferences,
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
        if state["intent"] == "search":
            return "search" if _has_search_criteria(state["preferences"]) else "clarify"
        if (
            state["intent"] == "show_results"
            and not state.get("ranked_listings")
            and not _has_search_criteria(state["preferences"])
        ):
            return "clarify"
        index = (state.get("relaxation_number") or 1) - 1
        if state["intent"] == "accept_relaxation":
            if 0 <= index < len(state.get("relaxations", [])):
                return "accept"
        if state["intent"] == "show_results" and not state.get("ranked_listings"):
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
        return {
            "preferences": state["preferences"].model_copy(
                update={suggestion["field"]: suggestion["suggested"]}
            )
        }

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
                "response_draft": (
                    "目前没有已展示的房源。你也可以直接提供房源编号，例如 S010。"
                )
            }
        if not numbers and not explicit_ids:
            return {
                "response_draft": (
                    f"目前展示了 {len(shown)} 套房源，请告诉我想收藏哪几套或房源编号。"
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
                problems.append(f"无效序号：{', '.join(map(str, invalid_numbers))}")
            if missing_ids:
                problems.append(f"未找到房源：{'、'.join(missing_ids)}")
            return {"response_draft": "；".join(problems) or "没有找到可加入的房源。"}

        shortlisted = list(
            dict.fromkeys([*state.get("shortlisted_listing_ids", []), *valid_ids])
        )
        response = f"已将房源 {'、'.join(valid_ids)} 加入候选清单。"
        if invalid_numbers:
            response += f" 无效序号已忽略：{', '.join(map(str, invalid_numbers))}。"
        if missing_ids:
            response += f" 未找到并已忽略：{'、'.join(missing_ids)}。"
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
            return {"response_draft": "候选清单目前是空的。"}
        if number is None and len(shortlisted) > 1:
            return {
                "response_draft": (
                    f"候选清单里有 {len(shortlisted)} 套房源，请告诉我不再考虑第几套。"
                )
            }

        index = (number or 1) - 1
        if not 0 <= index < len(shortlisted):
            return {
                "response_draft": f"请提供 1 到 {len(shortlisted)} 之间的候选房源序号。"
            }

        listing_id = shortlisted[index]
        ranked = [
            item
            for item in state.get("ranked_listings", [])
            if item["listing"]["listing_id"] != listing_id
        ]
        response = f"已将房源 {listing_id} 从候选清单移除，并从当前搜索结果排除。"
        response += (
            f"\n\n{render_response(ranked, state.get('restrictions'))}"
            if ranked
            else "\n\n当前没有剩余的匹配房源。"
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
            return {"response_draft": "候选清单目前是空的。"}

        listings = get_listings_by_ids(connection, listing_ids)
        ranked_by_id = {
            item["listing"]["listing_id"]: item
            for item in rank_listings(listings, state["preferences"])
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
                heading=f"候选清单共有 {len(ranked)} 套房源：",
                limit=len(ranked),
            ),
            "shown_listing_ids": [
                item["listing"]["listing_id"] for item in ranked
            ],
        }

    def clarification_node(state: AgentState):
        missing = _open_preferences(state["preferences"])
        return {
            "missing_preferences": missing,
            "response_draft": (
                "请至少告诉我一个搜索条件，例如每月预算、地区（如 D05）、"
                "房型或可接受的 MRT 步行时间。"
            ),
        }

    def prepare_search_node(state: AgentState):
        return {
            "listings": [],
            "restrictions": {},
            "ranked_listings": [],
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
        ranked = rank_listings(listings, preferences)
        return {
            "response_draft": render_relaxation_preview(
                suggestion,
                ranked,
                restrictions,
            ),
            "shown_listing_ids": _shown_listing_ids(ranked),
        }

    def search_node(state: AgentState):
        return {
            "listings": search_listings(
                connection,
                state["preferences"],
                _search_exclusions(state),
            )
        }

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

    def relaxation_node(state: AgentState):
        return {
            "relaxations": analyze_relaxations(
                connection,
                state["preferences"],
                _search_exclusions(state),
            )
        }

    def route_after_search(state: AgentState):
        return "matches" if state["listings"] else "no_matches"

    def respond_node(state: AgentState):
        ranked = state.get("ranked_listings", [])
        missing = _open_preferences(state["preferences"])
        response = render_response(
            ranked,
            state.get("restrictions"),
            state.get("relaxations"),
        )
        excluded = state.get("last_excluded_listing_ids", [])
        if excluded:
            response = f"已排除房源 {', '.join(excluded)}。\n\n{response}"
        if ranked and missing:
            response += (
                f"\n\n如果想继续缩小范围，可以补充"
                f"{_REFINEMENT_LABELS[missing[0]]}。"
            )
        return {
            "response_draft": response,
            "shown_listing_ids": _shown_listing_ids(ranked),
            "missing_preferences": missing,
        }

    def conversation_node(state: AgentState):
        response = render_intent_response(
            state["intent"],
            state.get("ranked_listings"),
            state.get("restrictions"),
            state.get("relaxations"),
        )
        update: AgentState = {"response_draft": response}
        if state["intent"] == "show_results" and state.get("ranked_listings"):
            update["shown_listing_ids"] = _shown_listing_ids(state["ranked_listings"])
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
                    ("system", _RESPONSE_PROMPT),
                    (
                        "human",
                        f"用户本轮消息：{state['message']}\n\n已验证事实草稿：\n{draft}",
                    ),
                ]
            )
        except Exception:
            return {"response": draft}
        content = getattr(reply, "content", None)
        return {
            "response": content.strip()
            if isinstance(content, str) and content.strip()
            else draft
        }

    graph = StateGraph(AgentState)
    graph.add_node("interpret", interpret_node)
    graph.add_node("apply_rejections", apply_rejections_node)
    graph.add_node("apply_relaxation", apply_relaxation_node)
    graph.add_node("shortlist", shortlist_node)
    graph.add_node("remove_shortlist", remove_shortlist_node)
    graph.add_node("show_shortlist", show_shortlist_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("prepare_search", prepare_search_node)
    graph.add_node("preview_relaxation", preview_relaxation_node)
    graph.add_node("search", search_node)
    graph.add_node("restrictions", restrictions_node)
    graph.add_node("rank", rank_node)
    graph.add_node("relaxation", relaxation_node)
    graph.add_node("respond", respond_node)
    graph.add_node("conversation", conversation_node)
    graph.add_node("generate_response", generate_response_node)
    graph.add_edge(START, "interpret")
    graph.add_conditional_edges(
        "interpret",
        route_after_interpret,
        {
            "search": "prepare_search",
            "clarify": "clarification",
            "reject": "apply_rejections",
            "accept": "apply_relaxation",
            "shortlist": "shortlist",
            "remove_shortlist": "remove_shortlist",
            "show_shortlist": "show_shortlist",
            "preview": "preview_relaxation",
            "conversation": "conversation",
        },
    )
    graph.add_edge("apply_rejections", "prepare_search")
    graph.add_edge("apply_relaxation", "prepare_search")
    graph.add_edge("shortlist", "generate_response")
    graph.add_edge("remove_shortlist", "generate_response")
    graph.add_edge("show_shortlist", "generate_response")
    graph.add_edge("prepare_search", "search")
    graph.add_conditional_edges(
        "search",
        route_after_search,
        {"matches": "restrictions", "no_matches": "relaxation"},
    )
    graph.add_edge("restrictions", "rank")
    graph.add_edge("rank", "respond")
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


def _listing_ids_in(message: str) -> list[str]:
    return list(
        dict.fromkeys(
            re.findall(r"(?<![A-Z0-9])S\d+(?![A-Z0-9])", message.upper())
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
    if preferences.room_type is None and not preferences.room_type_flexible:
        missing.append("room_type")
    if preferences.move_in_date is None and not preferences.move_in_flexible:
        missing.append("move_in_date")
    return missing


def _has_search_criteria(preferences: SearchPreferences) -> bool:
    return any(
        (
            preferences.max_price_sgd is not None,
            preferences.room_type is not None,
            preferences.district_code is not None,
            preferences.max_mrt_minutes is not None,
            preferences.verified_only,
            preferences.move_in_date is not None,
            preferences.cooking_required,
            preferences.ranking_priority != "balanced",
        )
    )
