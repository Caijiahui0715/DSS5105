import unittest
from contextlib import closing
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from graph import build_graph
from mock_db import create_mock_database
from models import ParsedTurn, SearchPreferences
from tools import search_listings


def _memory() -> MemorySaver:
    return MemorySaver(
        serde=JsonPlusSerializer(
            allowed_msgpack_modules=[("models", "SearchPreferences")]
        )
    )


class GraphTest(unittest.TestCase):
    def test_parse_search_and_restrictions_flow(self):
        preferences = SearchPreferences(
            max_price_sgd=1_300,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
            ranking_priority="mrt",
        )
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search", preferences=preferences
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {
                    "message": (
                        "预算1300，D05的common room，地铁10分钟内，"
                        "只看认证房源，比较倾向MTR近一点"
                    )
                }
            )

        self.assertEqual(result["preferences"], preferences)
        self.assertEqual(
            [listing["listing_id"] for listing in result["listings"]],
            ["S001", "S010"],
        )
        self.assertEqual(result["restrictions"]["S001"]["cooking"], "allowed")
        self.assertEqual(result["restrictions"]["S010"]["cooking"], "not_allowed")
        ranking = result["ranked_listings"]
        self.assertEqual(
            [item["listing"]["listing_id"] for item in ranking],
            ["S010", "S001"],
        )
        self.assertEqual([item["rank_value"] for item in ranking], [0.575, 0.767])
        self.assertEqual(ranking[0]["factors"]["mrt"]["weight"], 0.7)
        self.assertIn("找到 2 套符合条件的房源", result["response"])
        self.assertLess(result["response"].index("S010"), result["response"].index("S001"))
        self.assertIn("排名权重：价格 30%，MRT 70%", result["response"])
        self.assertIn("不允许做饭", result["response"])

    def test_no_results_returns_only_working_relaxations(self):
        preferences = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
        )
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search", preferences=preferences
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "预算1100，D05普通房，地铁10分钟内，只看认证房源"}
            )

        self.assertEqual(result["listings"], [])
        self.assertEqual(result["ranked_listings"], [])
        self.assertEqual(result["preferences"], preferences)
        self.assertEqual(
            result["relaxations"],
            [
                {
                    "field": "max_price_sgd",
                    "current": 1_100,
                    "suggested": 1_210,
                    "match_count": 1,
                }
            ],
        )
        self.assertIn("没有找到完全符合条件的房源", result["response"])
        self.assertIn("S$1,100 提高到 S$1,210", result["response"])

    def test_show_results_then_accepts_first_relaxation(self):
        preferences = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
        )
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="show_results", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "accept-relaxation"}}
            first = graph.invoke(
                {"message": "预算1100，D05普通房，地铁10分钟内，只看认证房源"},
                config=config,
            )
            second = graph.invoke({"message": "给我看看房源信息"}, config=config)
            third = graph.invoke({"message": "可以"}, config=config)

        self.assertEqual(first["relaxations"][0]["suggested"], 1_210)
        self.assertEqual(second["intent"], "show_results")
        self.assertEqual(second["preferences"].max_price_sgd, 1_100)
        self.assertIn("尚未修改你的原搜索条件", second["response"])
        self.assertIn("S001", second["response"])
        self.assertEqual(third["preferences"].max_price_sgd, 1_210)
        self.assertEqual(third["preferences"].district_code, "D05")
        self.assertEqual(
            [listing["listing_id"] for listing in third["listings"]],
            ["S001"],
        )
        self.assertIn("找到 1 套符合条件的房源", third["response"])
        self.assertEqual(structured_model.invoke.call_count, 2)

    def test_rejects_relaxation_without_changing_preferences(self):
        preferences = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
        )
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="reject_relaxation", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "reject-relaxation"}}
            first = graph.invoke({"message": "预算1100，D05普通房"}, config=config)
            second = graph.invoke({"message": "不提高预算"}, config=config)

        self.assertTrue(first["relaxations"])
        self.assertEqual(second["preferences"], preferences)
        self.assertEqual(second["relaxations"], [])
        self.assertIn("保留原来的搜索条件", second["response"])

    def test_shows_saved_results_without_searching_again(self):
        preferences = SearchPreferences(
            max_price_sgd=1_300,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
        )
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="show_results", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with (
            closing(create_mock_database()) as connection,
            patch("graph.search_listings", wraps=search_listings) as search,
        ):
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "show-saved-results"}}
            first = graph.invoke({"message": "预算1300，D05普通房"}, config=config)
            second = graph.invoke({"message": "再给我看看这些房源"}, config=config)

        self.assertEqual(search.call_count, 1)
        self.assertEqual(second["ranked_listings"], first["ranked_listings"])
        self.assertIn("S001", second["response"])
        self.assertIn("S010", second["response"])

    def test_partial_update_preserves_other_preferences(self):
        original = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
            ranking_priority="mrt",
        )
        updated = original.model_copy(update={"max_price_sgd": 1_300})
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=original),
            ParsedTurn(intent="search", preferences=updated),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "partial-update"}}
            graph.invoke({"message": "预算1100，D05普通房"}, config=config)
            result = graph.invoke({"message": "预算改成1300"}, config=config)

        self.assertEqual(result["preferences"], updated)
        self.assertEqual(
            [item["listing"]["listing_id"] for item in result["ranked_listings"]],
            ["S010", "S001"],
        )

    def test_invalid_relaxation_number_returns_guidance(self):
        preferences = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
            verified_only=True,
        )
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(
                intent="accept_relaxation",
                preferences=preferences,
                relaxation_number=2,
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "invalid-relaxation"}}
            graph.invoke({"message": "预算1100，D05普通房"}, config=config)
            result = graph.invoke({"message": "接受第二个建议"}, config=config)

        self.assertEqual(result["preferences"], preferences)
        self.assertEqual(len(result["relaxations"]), 1)
        self.assertIn("没有可接受的让步建议", result["response"])


if __name__ == "__main__":
    unittest.main()
