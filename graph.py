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
    rank_listings,
    search_listings,
)


class AgentState(TypedDict, total=False):
    message: str
    intent: UserIntent
    relaxation_number: int | None
    preferences: SearchPreferences
    listings: list[Listing]
    restrictions: dict[str, RestrictionSummary]
    ranked_listings: list[RankingResult]
    relaxations: list[RelaxationSuggestion]
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


def build_graph(connection: sqlite3.Connection, model: Any, checkpointer=None):
    def interpret_node(state: AgentState):
        previous = state.get("preferences")
        relaxations = state.get("relaxations", [])
        if previous and relaxations and _accepts_first(state["message"]):
            return {"intent": "accept_relaxation", "relaxation_number": 1}

        turn = parse_turn(
            state["message"],
            model,
            previous,
            relaxations,
            bool(state.get("ranked_listings")),
        )
        return {
            "intent": turn.intent,
            "relaxation_number": turn.relaxation_number,
            "preferences": turn.preferences,
        }

    def route_after_interpret(state: AgentState):
        if state["intent"] == "search":
            return "search"
        index = (state.get("relaxation_number") or 1) - 1
        if state["intent"] == "accept_relaxation":
            if 0 <= index < len(state.get("relaxations", [])):
                return "accept"
        if state["intent"] == "show_results" and not state.get("ranked_listings"):
            if 0 <= index < len(state.get("relaxations", [])):
                return "preview"
        return "conversation"

    def apply_relaxation_node(state: AgentState):
        index = (state.get("relaxation_number") or 1) - 1
        suggestion = state["relaxations"][index]
        return {
            "preferences": state["preferences"].model_copy(
                update={suggestion["field"]: suggestion["suggested"]}
            )
        }

    def prepare_search_node(state: AgentState):
        return {
            "listings": [],
            "restrictions": {},
            "ranked_listings": [],
            "relaxations": [],
        }

    def preview_relaxation_node(state: AgentState):
        index = (state.get("relaxation_number") or 1) - 1
        suggestion = state["relaxations"][index]
        preferences = state["preferences"].model_copy(
            update={suggestion["field"]: suggestion["suggested"]}
        )
        listings = search_listings(connection, preferences)
        restrictions = {
            listing["listing_id"]: extract_restrictions(listing)
            for listing in listings
        }
        return {
            "response": render_relaxation_preview(
                suggestion,
                rank_listings(listings, preferences),
                restrictions,
            )
        }

    def search_node(state: AgentState):
        return {"listings": search_listings(connection, state["preferences"])}

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
            "relaxations": analyze_relaxations(connection, state["preferences"])
        }

    def route_after_search(state: AgentState):
        return "matches" if state["listings"] else "no_matches"

    def respond_node(state: AgentState):
        return {
            "response": render_response(
                state.get("ranked_listings"),
                state.get("restrictions"),
                state.get("relaxations"),
            )
        }

    def conversation_node(state: AgentState):
        response = render_intent_response(
            state["intent"],
            state.get("ranked_listings"),
            state.get("restrictions"),
            state.get("relaxations"),
        )
        update: AgentState = {"response": response}
        if state["intent"] == "reject_relaxation":
            update["relaxations"] = []
        return update

    graph = StateGraph(AgentState)
    graph.add_node("interpret", interpret_node)
    graph.add_node("apply_relaxation", apply_relaxation_node)
    graph.add_node("prepare_search", prepare_search_node)
    graph.add_node("preview_relaxation", preview_relaxation_node)
    graph.add_node("search", search_node)
    graph.add_node("restrictions", restrictions_node)
    graph.add_node("rank", rank_node)
    graph.add_node("relaxation", relaxation_node)
    graph.add_node("respond", respond_node)
    graph.add_node("conversation", conversation_node)
    graph.add_edge(START, "interpret")
    graph.add_conditional_edges(
        "interpret",
        route_after_interpret,
        {
            "search": "prepare_search",
            "accept": "apply_relaxation",
            "preview": "preview_relaxation",
            "conversation": "conversation",
        },
    )
    graph.add_edge("apply_relaxation", "prepare_search")
    graph.add_edge("prepare_search", "search")
    graph.add_conditional_edges(
        "search",
        route_after_search,
        {"matches": "restrictions", "no_matches": "relaxation"},
    )
    graph.add_edge("restrictions", "rank")
    graph.add_edge("rank", "respond")
    graph.add_edge("relaxation", "respond")
    graph.add_edge("respond", END)
    graph.add_edge("conversation", END)
    graph.add_edge("preview_relaxation", END)
    return graph.compile(checkpointer=checkpointer)


def _accepts_first(message: str) -> bool:
    return message.casefold().strip(" \t\r\n。！!，,") in _ACCEPT_FIRST
