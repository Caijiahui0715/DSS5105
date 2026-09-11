import unittest
from contextlib import closing
from unittest.mock import Mock

from graph import build_graph
from mock_db import create_mock_database
from models import SearchPreferences


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
        structured_model.invoke.return_value = preferences
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
        structured_model.invoke.return_value = preferences
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "预算1100，D05普通房，地铁10分钟内，只看认证房源"}
            )

        self.assertEqual(result["listings"], [])
        self.assertNotIn("ranked_listings", result)
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


if __name__ == "__main__":
    unittest.main()
