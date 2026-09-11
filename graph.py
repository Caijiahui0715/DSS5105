import sqlite3
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from models import (
    Listing,
    RankingResult,
    RelaxationSuggestion,
    RestrictionSummary,
    SearchPreferences,
)
from parser import parse_preferences
from response import render_response
from tools import (
    analyze_relaxations,
    extract_restrictions,
    rank_listings,
    search_listings,
)


class AgentState(TypedDict, total=False):
    message: str
    preferences: SearchPreferences
    listings: list[Listing]
    restrictions: dict[str, RestrictionSummary]
    ranked_listings: list[RankingResult]
    relaxations: list[RelaxationSuggestion]
    response: str


def build_graph(connection: sqlite3.Connection, model: Any):
    def parse_node(state: AgentState):
        return {"preferences": parse_preferences(state["message"], model)}

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

    graph = StateGraph(AgentState)
    graph.add_node("parse", parse_node)
    graph.add_node("search", search_node)
    graph.add_node("restrictions", restrictions_node)
    graph.add_node("rank", rank_node)
    graph.add_node("relaxation", relaxation_node)
    graph.add_node("respond", respond_node)
    graph.add_edge(START, "parse")
    graph.add_edge("parse", "search")
    graph.add_conditional_edges(
        "search",
        route_after_search,
        {"matches": "restrictions", "no_matches": "relaxation"},
    )
    graph.add_edge("restrictions", "rank")
    graph.add_edge("rank", "respond")
    graph.add_edge("relaxation", "respond")
    graph.add_edge("respond", END)
    return graph.compile()
