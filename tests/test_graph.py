import unittest
from contextlib import closing
from datetime import date
from unittest.mock import Mock, patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from graph import _has_search_criteria, _listing_ids_in, _open_preferences, _response_language, build_graph
from mock_db import create_mock_database
from models import ParsedTurn, SearchPreferences
from tools import search_listings


def _memory() -> MemorySaver:
    return MemorySaver(
        serde=JsonPlusSerializer(
            allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation")]
        )
    )


class GraphTest(unittest.TestCase):
    def test_recognizes_real_propertyguru_listing_ids(self):
        self.assertEqual(
            _listing_ids_in("比较 500253628 和 24534844"),
            ["500253628", "24534844"],
        )
        self.assertEqual(_listing_ids_in("预算 1100，MRT 10 分钟"), [])

    def test_graph_removes_redirected_results_before_responding(self):
        preferences = SearchPreferences(
            max_price_sgd=1_300,
            room_type="common_room",
            district_code="D05",
        )
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search", preferences=preferences
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model

        def checker(listing_id, url):
            return {
                "status": "inactive" if listing_id == "S010" else "active",
                "final_url": url,
                "http_status": 200,
            }

        with closing(create_mock_database()) as connection:
            connection.execute(
                "DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')"
            )
            result = build_graph(
                connection,
                model,
                listing_checker=checker,
            ).invoke({"message": "预算1300，D05 common room"})

        self.assertEqual(result["shown_listing_ids"], ["S001"])
        self.assertNotIn("S010", result["response_draft"])

    def test_all_strict_links_inactive_routes_to_checked_relaxation_and_preview(self):
        preferences = SearchPreferences(max_price_sgd=1_200, room_type="common_room", district_code="D05")
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="show_results", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model
        checked_ids = []

        def checker(listing_id, url):
            checked_ids.append(listing_id)
            return {
                "status": "active" if listing_id == "S010" else "inactive",
                "final_url": url,
            }

        with closing(create_mock_database()) as connection:
            connection.execute("DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')")
            graph = build_graph(connection, model, _memory(), listing_checker=checker)
            config = {"configurable": {"thread_id": "inactive-to-relaxation"}}
            first = graph.invoke({"message": "预算1200，D05 common room"}, config=config)
            preview = graph.invoke({"message": "给我看看"}, config=config)
            accepted = graph.invoke({"message": "可以"}, config=config)

        self.assertEqual(first["ranked_listings"], [])
        self.assertEqual(first["listing_check_summary"]["inactive_count"], 1)
        self.assertEqual(first["relaxations"][0]["match_count"], 1)
        self.assertEqual(first["relaxations"][0]["check_summary"]["active_count"], 1)
        self.assertEqual(first["preferences"], preferences)
        self.assertEqual(preview["preferences"], preferences)
        self.assertEqual(preview["shown_listing_ids"], ["S010"])
        self.assertEqual(len(preview["shown_listing_ids"]), first["relaxations"][0]["match_count"])
        self.assertIn("尚未修改你的原搜索条件", preview["response_draft"])
        self.assertIn("原链接失效 1 套", first["response_draft"])
        self.assertEqual(checked_ids, ["S001", "S010"])
        self.assertEqual(accepted["preferences"].max_price_sgd, 1_320)
        self.assertEqual(accepted["shown_listing_ids"], ["S010"])

    def test_unknown_strict_links_are_kept_and_do_not_trigger_relaxation(self):
        preferences = SearchPreferences(max_price_sgd=1_300, room_type="common_room", district_code="D05")
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(intent="search", preferences=preferences)
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection, patch("graph.analyze_relaxations") as relax:
            connection.execute("DELETE FROM listing_health WHERE listing_id IN ('S001', 'S010')")
            result = build_graph(
                connection,
                model,
                listing_checker=lambda *_: {"status": "unknown", "error_reason": "http_403"},
            ).invoke({"message": "预算1300，D05 common room"})

        relax.assert_not_called()
        self.assertEqual(result["shown_listing_ids"], ["S010", "S001"])
        self.assertEqual(result["listing_check_summary"]["unknown_count"], 2)
        self.assertEqual(result["preferences"], preferences)
        self.assertIn("HTTP 403", result["response_draft"])
        self.assertIn("这不表示房源已下架", result["response_draft"])

    def test_preview_updates_a_changed_count_without_changing_preferences(self):
        preferences = SearchPreferences(max_price_sgd=1_100, room_type="common_room", district_code="D05")
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="show_results", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "changed-preview"}}
            first = graph.invoke({"message": "预算1100，D05 common room"}, config=config)
            connection.execute("UPDATE listing_health SET status = 'inactive' WHERE listing_id = 'S001'")
            preview = graph.invoke({"message": "给我看看"}, config=config)

        self.assertEqual(first["relaxations"][0]["match_count"], 1)
        self.assertEqual(preview["relaxations"][0]["match_count"], 0)
        self.assertEqual(preview["shown_listing_ids"], [])
        self.assertEqual(preview["preferences"], preferences)
        self.assertIn("本次检查结果已更新", preview["response_draft"])
        self.assertIn("尚未修改你的原搜索条件", preview["response_draft"])

    def test_converts_a_foreign_budget_before_searching(self):
        preferences = SearchPreferences(room_type="Shared Room")
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search",
            preferences=preferences,
            budget_amount=5_000,
            budget_currency="CNY",
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model
        conversion = {
            "original_amount": 5_000,
            "original_currency": "CNY",
            "rate_to_sgd": "0.18",
            "rate_date": "2026-09-15",
            "amount_sgd": 900,
        }

        with (
            closing(create_mock_database()) as connection,
            patch("graph.convert_to_sgd", return_value=conversion) as convert,
        ):
            result = build_graph(connection, model).invoke(
                {"message": "我的预算是5000人民币，想找Shared Room"}
            )

        convert.assert_called_once_with(5_000, "CNY")
        self.assertEqual(result["preferences"].max_price_sgd, 900)
        self.assertEqual(result["budget_conversion"], conversion)
        self.assertEqual(
            [listing["listing_id"] for listing in result["listings"]],
            ["S004"],
        )
        self.assertIn("5,000 CNY", result["response_draft"])
        self.assertIn("S$900", result["response_draft"])

    def test_a_yearly_budget_is_spread_over_twelve_months(self):
        conversion = {
            "original_amount": 300_000,
            "original_currency": "CNY",
            "rate_to_sgd": "0.19094",
            "rate_date": "2026-10-05",
            "amount_sgd": 57_282,
        }
        cases = (
            ("一年的预算是30万人民币", 300_000, "CNY", {**conversion, "months": 12, "monthly_sgd": 4_773}, 4_773),
            ("每年预算6万新币", 60_000, "SGD", {"original_amount": 60_000, "original_currency": "SGD", "amount_sgd": 60_000, "months": 12, "monthly_sgd": 5_000}, 5_000),
        )
        for message, amount, currency, expected, monthly in cases:
            structured_model = Mock()
            structured_model.invoke.return_value = ParsedTurn(
                intent="search",
                preferences=SearchPreferences(),
                budget_amount=amount,
                budget_currency=currency,
                budget_months=12,
            )
            model = Mock()
            model.with_structured_output.return_value = structured_model
            with (
                self.subTest(message=message),
                closing(create_mock_database()) as connection,
                patch("graph.convert_to_sgd", return_value=conversion),
            ):
                result = build_graph(connection, model).invoke({"message": message})

                self.assertEqual(result["preferences"].max_price_sgd, monthly)
                self.assertEqual(result["budget_conversion"], expected)
                self.assertIn(f"÷ 12 = 每月 S${monthly:,}", result["response_draft"])

    def test_does_not_search_with_an_ambiguous_currency_symbol(self):
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search",
            preferences=SearchPreferences(),
            budget_amount=5_000,
            budget_currency=None,
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with (
            closing(create_mock_database()) as connection,
            patch("graph.search_listings", wraps=search_listings) as search,
        ):
            result = build_graph(connection, model).invoke(
                {"message": "我的预算是¥5000"}
            )

        search.assert_not_called()
        self.assertEqual(result["budget_conversion_error"], "ambiguous_currency")
        self.assertIn("预算币种符号不明确", result["response_draft"])

    def test_detects_or_preserves_the_response_language(self):
        self.assertEqual(_response_language("Find me a room"), "en")
        self.assertEqual(_response_language("帮我找房"), "zh")
        self.assertEqual(_response_language("S010", "en"), "en")
        self.assertEqual(_response_language("yes", "zh"), "zh")
        self.assertEqual(_response_language("请用英文回答", "zh"), "en")

    def test_english_input_rejects_a_wrong_language_response(self):
        preferences = SearchPreferences(max_price_sgd=1_100)
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search", preferences=preferences
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model
        model.invoke.return_value.content = "找到两套房源。"

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "My monthly budget is 1100 SGD"}
            )

        self.assertEqual(result["response_language"], "en")
        self.assertEqual(result["response"], result["response_draft"])
        self.assertIn("Found 2 matching listings", result["response"])
        self.assertIn("Monthly rent: S$850", result["response"])
        prompt = model.invoke.call_args.args[0]
        self.assertIn("Reply only in English", prompt[0][1])
        self.assertIn("Verified factual draft", prompt[-1][1])

    def test_searches_first_then_refines_preferences_across_turns(self):
        district_only = SearchPreferences(district_code="D05")
        with_budget = district_only.model_copy(update={"max_price_sgd": 1_100})
        flexible_room = with_budget.model_copy(update={"room_type_flexible": True})
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=district_only),
            ParsedTurn(intent="search", preferences=with_budget),
            ParsedTurn(intent="search", preferences=flexible_room),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with (
            closing(create_mock_database()) as connection,
            patch("graph.search_listings", wraps=search_listings) as search,
        ):
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "progressive-search"}}
            first = graph.invoke({"message": "帮我找D05的房"}, config=config)
            second = graph.invoke(
                {"message": "我的预算是1100"},
                config=config,
            )
            third = graph.invoke(
                {"message": "这些房型我都可以"},
                config=config,
            )

        self.assertEqual(search.call_count, 3)
        self.assertEqual(first["preferences"], district_only)
        self.assertTrue(first["ranked_listings"])
        self.assertIn("最高预算", first["response_draft"])
        self.assertEqual(second["preferences"], with_budget)
        self.assertEqual(
            [listing["listing_id"] for listing in second["listings"]],
            ["S004"],
        )
        self.assertEqual(third["preferences"], flexible_room)
        self.assertNotIn("room_type", third["missing_preferences"])

    def test_refinements_ask_whole_unit_or_room_before_room_type(self):
        self.assertEqual(_open_preferences(SearchPreferences(max_price_sgd=1_000)), ["rental_scope", "move_in_date"])
        self.assertEqual(
            _open_preferences(SearchPreferences(rental_scope="room")),
            ["max_price_sgd", "room_type", "move_in_date"],
        )
        self.assertEqual(_open_preferences(SearchPreferences(rental_scope="entire_unit")), ["max_price_sgd", "move_in_date"])
        # A named room type already says it is a room.
        self.assertEqual(_open_preferences(SearchPreferences(room_type="common_room")), ["max_price_sgd", "move_in_date"])
        self.assertTrue(_has_search_criteria(SearchPreferences(tenant_gender="female")))
        self.assertTrue(_has_search_criteria(SearchPreferences(max_commute_minutes=40)))

    def test_clarifies_only_when_no_search_criteria_exist(self):
        preferences = SearchPreferences()
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search", preferences=preferences
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with (
            closing(create_mock_database()) as connection,
            patch("graph.search_listings", wraps=search_listings) as search,
        ):
            result = build_graph(connection, model).invoke({"message": "帮我找房"})

        self.assertEqual(search.call_count, 0)
        self.assertIn("至少告诉我一个搜索条件", result["response_draft"])

    def test_model_rewrites_the_verified_response_draft(self):
        preferences = SearchPreferences(
            max_price_sgd=1_300,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
        )
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search", preferences=preferences
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model
        model.invoke.return_value.content = "我找到了两套房，先从更匹配的开始看。"

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "帮我找D05的普通房"}
            )

        self.assertEqual(result["response"], "我找到了两套房，先从更匹配的开始看。")
        self.assertIn("S010", result["response_draft"])
        self.assertIn("S001", result["response_draft"])
        prompt = model.invoke.call_args.args[0]
        self.assertIn("已验证事实草稿", prompt[-1][1])

    def test_rejects_an_invented_offer_to_confirm_future_availability(self):
        preferences = SearchPreferences(
            max_price_sgd=4_800,
            room_type="Shared Room",
            move_in_date=date(2026, 10, 5),
            cooking_required=True,
        )
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="search", preferences=preferences
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model
        model.invoke.return_value.content = (
            "需要我帮你确认这套是否接受 10 月 5 日入住吗？"
        )

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "预算4800，Shared Room，可以做饭，10月5日入住"}
            )

        self.assertEqual(result["response"], result["response_draft"])
        self.assertIn("无法确认房源届时仍然可租", result["response"])
        self.assertIn("不能代为联系发布方", result["response"])
        prompt = model.invoke.call_args.args[0]
        self.assertIn("cannot contact landlords", prompt[0][1])

    def test_parse_search_and_restrictions_flow(self):
        preferences = SearchPreferences(
            max_price_sgd=1_300,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
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
        self.assertEqual([item["rank_value"] for item in ranking], [0.551, 0.738])
        self.assertEqual(ranking[0]["factors"]["mrt"]["weight"], 0.7)
        self.assertIn("找到 2 套符合条件的房源", result["response"])
        self.assertLess(result["response"].index("S010"), result["response"].index("S001"))
        self.assertIn("排名权重：MRT 70%，价格 30%", result["response"])
        self.assertIn("不允许做饭", result["response"])

    def test_no_results_returns_only_working_relaxations(self):
        preferences = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
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
                    "check_summary": {
                        "database_match_count": 1,
                        "checked_count": 1,
                        "active_count": 1,
                        "unknown_count": 0,
                        "inactive_count": 0,
                        "unchecked_count": 0,
                    },
                }
            ],
        )
        self.assertIn("当前没有可展示的严格匹配房源", result["response"])
        self.assertIn("S$1,100 提高到 S$1,210", result["response"])

    def test_show_results_then_accepts_first_relaxation(self):
        preferences = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
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

    def test_rejects_preview_and_new_results_while_updating_budget(self):
        original = SearchPreferences(
            max_price_sgd=1_100,
            room_type="Common Room",
            district_code="D05",
            max_mrt_minutes=10,
        )
        updated = original.model_copy(update={"max_price_sgd": 1_400})
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=original),
            ParsedTurn(intent="show_results", preferences=original),
            ParsedTurn(
                intent="search",
                preferences=updated,
                reject_all_shown=True,
            ),
            ParsedTurn(
                intent="reject_results",
                preferences=updated,
                reject_all_shown=True,
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "reject-results"}}
            graph.invoke({"message": "预算1100，D05普通房"}, config=config)
            preview = graph.invoke({"message": "给我看看"}, config=config)
            updated_results = graph.invoke(
                {"message": "我不想要这套房，预算可以提高到1400"},
                config=config,
            )
            rejected_results = graph.invoke(
                {"message": "这些房都不行"},
                config=config,
            )

        self.assertEqual(preview["shown_listing_ids"], ["S001"])
        self.assertEqual(updated_results["excluded_listing_ids"], ["S001"])
        self.assertIn("已排除房源 S001", updated_results["response_draft"])
        self.assertEqual(
            [
                item["listing"]["listing_id"]
                for item in updated_results["ranked_listings"]
            ],
            ["S010", "S006"],
        )
        self.assertEqual(
            rejected_results["excluded_listing_ids"],
            ["S001", "S010", "S006"],
        )
        self.assertEqual(rejected_results["listings"], [])
        self.assertNotIn("我还不确定", rejected_results["response"])

    def test_shortlists_the_only_shown_listing_without_asking_for_its_number(self):
        preferences = SearchPreferences(
            max_price_sgd=1_210,
            room_type="Common Room",
            district_code="D05",
        )
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="shortlist_listing", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "shortlist-one"}}
            first = graph.invoke({"message": "预算1210，D05普通房"}, config=config)
            result = graph.invoke({"message": "我会考虑这套"}, config=config)

        self.assertEqual(first["shown_listing_ids"], ["S001"])
        self.assertEqual(result["shortlisted_listing_ids"], ["S001"])
        self.assertIn("已将房源 S001 加入候选清单", result["response_draft"])

    def test_asks_which_listing_when_multiple_are_shown(self):
        preferences = SearchPreferences(district_code="D05")
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="shortlist_listing", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "shortlist-many"}}
            first = graph.invoke({"message": "帮我找D05的房"}, config=config)
            result = graph.invoke({"message": "我会考虑这套"}, config=config)

        self.assertGreater(len(first["shown_listing_ids"]), 1)
        self.assertNotIn("shortlisted_listing_ids", result)
        self.assertIn("请告诉我想收藏哪几套", result["response_draft"])

    def test_shortlists_a_numbered_listing_and_keeps_existing_choices(self):
        preferences = SearchPreferences(district_code="D05")
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=preferences,
                shortlist_listing_numbers=[2],
            ),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=preferences,
                shortlist_listing_numbers=[1],
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "shortlist-numbered"}}
            first = graph.invoke({"message": "帮我找D05的房"}, config=config)
            second = graph.invoke({"message": "收藏第二套"}, config=config)
            result = graph.invoke({"message": "第一套也收藏"}, config=config)

        self.assertEqual(
            result["shortlisted_listing_ids"],
            [first["shown_listing_ids"][1], first["shown_listing_ids"][0]],
        )

    def test_removes_and_excludes_the_only_shortlisted_listing(self):
        preferences = SearchPreferences(max_mrt_minutes=5, ranking_priority="mrt")
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=preferences,
                shortlist_listing_numbers=[1],
            ),
            ParsedTurn(
                intent="remove_shortlisted_listing",
                preferences=preferences,
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "remove-shortlisted"}}
            first = graph.invoke({"message": "MRT步行5分钟"}, config=config)
            shortlisted = graph.invoke({"message": "我想要第一套"}, config=config)
            result = graph.invoke(
                {"message": "我不想要刚刚列入清单的那一套了"},
                config=config,
            )

        self.assertEqual(first["shown_listing_ids"], ["S010", "S006", "S007"])
        self.assertEqual(shortlisted["shortlisted_listing_ids"], ["S010"])
        self.assertEqual(result["shortlisted_listing_ids"], [])
        self.assertEqual(result["excluded_listing_ids"], ["S010"])
        self.assertEqual(result["shown_listing_ids"], ["S006", "S007"])
        self.assertIn("已将房源 S010", result["response"])
        self.assertIn("S006", result["response"])
        self.assertIn("S007", result["response"])

    def test_shows_shortlist_without_overwriting_current_search_results(self):
        mrt_search = SearchPreferences(max_mrt_minutes=5, ranking_priority="mrt")
        district_search = mrt_search.model_copy(update={"district_code": "D22"})
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=mrt_search),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=mrt_search,
                shortlist_listing_numbers=[1],
            ),
            ParsedTurn(intent="search", preferences=district_search),
            ParsedTurn(intent="show_results", preferences=district_search),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "show-shortlist"}}
            graph.invoke({"message": "MRT步行5分钟"}, config=config)
            graph.invoke({"message": "收藏第一套"}, config=config)
            current = graph.invoke({"message": "只看D22"}, config=config)
            shortlist = graph.invoke(
                {"message": "我能看看目前的候选清单吗\\"},
                config=config,
            )
            current_again = graph.invoke({"message": "查看搜索结果"}, config=config)

        self.assertEqual(current["shown_listing_ids"], ["S007"])
        self.assertEqual(shortlist["shortlisted_listing_ids"], ["S010"])
        self.assertIn("S010", shortlist["response_draft"])
        self.assertNotIn("S007", shortlist["response_draft"])
        self.assertEqual(shortlist["ranked_listings"], current["ranked_listings"])
        self.assertEqual(current_again["shown_listing_ids"], ["S007"])

    def test_relaxes_search_after_other_results_are_shortlisted_or_rejected(self):
        preferences = SearchPreferences(max_price_sgd=1_100)
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=preferences,
                shortlist_listing_numbers=[1],
            ),
            ParsedTurn(
                intent="reject_results",
                preferences=preferences,
                rejected_listing_numbers=[2],
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "shortlist-and-relax"}}
            first = graph.invoke({"message": "预算1100"}, config=config)
            shortlisted = graph.invoke({"message": "收藏第一套"}, config=config)
            result = graph.invoke(
                {"message": "第二套我不喜欢，还有什么可以推荐的"},
                config=config,
            )

        self.assertEqual(first["shown_listing_ids"], ["S002", "S004"])
        self.assertEqual(shortlisted["shortlisted_listing_ids"], ["S002"])
        self.assertEqual(result["excluded_listing_ids"], ["S004"])
        self.assertEqual(result["shortlisted_listing_ids"], ["S002"])
        self.assertEqual(result["listings"], [])
        self.assertEqual(result["ranked_listings"], [])
        self.assertEqual(result["relaxations"][0]["field"], "max_price_sgd")
        self.assertEqual(result["relaxations"][0]["suggested"], 1_210)
        self.assertIn("S$1,100 提高到 S$1,210", result["response"])

    def test_show_shortlist_cannot_be_misclassified_as_current_results(self):
        original = SearchPreferences(max_price_sgd=1_100)
        expanded = original.model_copy(update={"max_price_sgd": 1_400})
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=original),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=original,
                shortlist_listing_numbers=[1],
            ),
            ParsedTurn(
                intent="reject_results",
                preferences=original,
                rejected_listing_numbers=[2],
            ),
            ParsedTurn(intent="search", preferences=expanded),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=expanded,
                shortlist_listing_numbers=[1],
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "shortlist-routing"}}
            graph.invoke({"message": "预算1100"}, config=config)
            graph.invoke({"message": "收藏第一套"}, config=config)
            graph.invoke({"message": "第二套我不喜欢"}, config=config)
            graph.invoke({"message": "预算提高到1400"}, config=config)
            graph.invoke({"message": "我喜欢第一套"}, config=config)
            result = graph.invoke(
                {"message": "我能看看目前的候选清单吗\\"},
                config=config,
            )

        self.assertEqual(structured_model.invoke.call_count, 5)
        self.assertEqual(result["intent"], "show_shortlist")
        self.assertEqual(result["shortlisted_listing_ids"], ["S002", "S010"])
        self.assertEqual(result["shown_listing_ids"], ["S002", "S010"])
        self.assertIn("S002", result["response"])
        self.assertIn("S010", result["response"])
        # Current results at S$1,400 that were not shortlisted stay out.
        self.assertNotIn("S006", result["response"])
        self.assertNotIn("S001", result["response"])

    def test_shortlists_multiple_explicit_ids_without_search_results(self):
        preferences = SearchPreferences()
        structured_model = Mock()
        structured_model.invoke.return_value = ParsedTurn(
            intent="shortlist_listing",
            preferences=preferences,
        )
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "帮我添加S010,S009房源到我的list里面"}
            )

        self.assertEqual(result["shortlist_listing_ids"], ["S010", "S009"])
        self.assertEqual(result["shortlisted_listing_ids"], ["S010", "S009"])
        self.assertIn("S010、S009", result["response"])

    def test_shortlists_multiple_displayed_positions_in_one_turn(self):
        preferences = SearchPreferences(max_price_sgd=5_000)
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=preferences,
                shortlist_listing_numbers=[1, 2],
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "shortlist-first-two"}}
            first = graph.invoke({"message": "预算5000"}, config=config)
            result = graph.invoke(
                {"message": "我喜欢前两套，帮我加入候选"},
                config=config,
            )

        self.assertEqual(first["shown_listing_ids"][:2], ["S010", "S006"])
        self.assertEqual(result["shortlisted_listing_ids"], ["S010", "S006"])
        self.assertIn("S010、S006", result["response"])

    def test_compares_all_shortlisted_listings(self):
        preferences = SearchPreferences(max_price_sgd=5_000)
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(
                intent="shortlist_listing",
                preferences=preferences,
                shortlist_listing_numbers=[1, 3],
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "compare-shortlist"}}
            graph.invoke({"message": "预算5000"}, config=config)
            graph.invoke({"message": "收藏第一套和第三套"}, config=config)
            result = graph.invoke({"message": "比较我的候选房源"}, config=config)

        self.assertEqual(structured_model.invoke.call_count, 2)
        self.assertEqual(result["intent"], "compare_shortlist")
        self.assertIn("最低月租：S002", result["response_draft"])
        self.assertIn("MRT 最近：S010", result["response_draft"])
        self.assertEqual(result["shown_listing_ids"], ["S010", "S002"])

    def test_compares_explicit_ids_without_a_shortlist(self):
        model = Mock()

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "比较 S010 和 S001 哪个好"}
            )

        model.with_structured_output.assert_not_called()
        self.assertEqual(result["compare_listing_ids"], ["S010", "S001"])
        self.assertIn("S010", result["response_draft"])
        self.assertIn("S001", result["response_draft"])
        self.assertIn("最低月租：S001", result["response_draft"])
        self.assertIn("MRT 最近：S010", result["response_draft"])

    def test_shows_explicit_listing_details_without_searching_first(self):
        model = Mock()

        with closing(create_mock_database()) as connection:
            result = build_graph(connection, model).invoke(
                {"message": "查看 S010 的详情"}
            )

        model.with_structured_output.assert_not_called()
        self.assertEqual(result["intent"], "show_listing_details")
        self.assertEqual(result["shown_listing_ids"], ["S010"])
        self.assertIn("Synthetic Second Room At Clementi Address", result["response_draft"])
        self.assertIn("Synthetic Block 606 Clementi Avenue", result["response_draft"])
        self.assertIn("不允许做饭", result["response_draft"])

    def test_shows_details_for_a_displayed_position(self):
        preferences = SearchPreferences(max_price_sgd=1_100)
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(
                intent="show_listing_details",
                preferences=preferences,
                detail_listing_number=2,
            ),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "details-number"}}
            graph.invoke({"message": "预算1100"}, config=config)
            result = graph.invoke({"message": "看看第二套的详情"}, config=config)

        self.assertEqual(result["shown_listing_ids"], ["S004"])
        self.assertIn("Synthetic Pasir Panjang Shared Room", result["response_draft"])
        self.assertIn("允许做饭", result["response_draft"])

    def test_resolves_this_listing_when_only_one_is_shown(self):
        preferences = SearchPreferences(district_code="D22")
        structured_model = Mock()
        structured_model.invoke.side_effect = [
            ParsedTurn(intent="search", preferences=preferences),
            ParsedTurn(intent="show_listing_details", preferences=preferences),
        ]
        model = Mock()
        model.with_structured_output.return_value = structured_model

        with closing(create_mock_database()) as connection:
            graph = build_graph(connection, model, _memory())
            config = {"configurable": {"thread_id": "details-this"}}
            graph.invoke({"message": "只看D22"}, config=config)
            result = graph.invoke({"message": "看看这套的详细信息"}, config=config)

        self.assertEqual(result["shown_listing_ids"], ["S007"])
        self.assertIn("Synthetic Jurong East Master Room", result["response_draft"])


if __name__ == "__main__":
    unittest.main()
