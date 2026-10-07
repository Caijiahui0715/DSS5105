import json
import unittest
from contextlib import closing
from datetime import date
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent import build_agent
from mock_db import create_database, create_mock_database
from exchange import CurrencyConversionError, UnknownCurrencyError
from models import SearchPreferences
from profiles import UserProfiles
from sessions import memory_storage


class ScriptedModel:
    """Returns prepared replies; a callable step receives the messages sent to the model."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []
        self.tools = []

    def bind_tools(self, tools, **_):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


def tool_calls(*calls):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call_{index}_{name}"}
            for index, (name, args) in enumerate(calls)
        ],
    )


def active_links(listing_id, url):
    return {"status": "active", "final_url": url, "http_status": 200}


def memory_agent(connection, model, profiles):
    """An agent with long-term memory; threads share one checkpointer like separate conversations."""
    return build_agent(
        connection,
        model,
        MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation")])),
        listing_checker=active_links,
        profiles=profiles,
    )


def say(graph, thread, message, user="alice"):
    return graph.invoke({"message": message, "user_id": user}, config={"configurable": {"thread_id": thread}})


def run_agent(connection, model, *messages):
    graph = build_agent(
        connection,
        model,
        MemorySaver(
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation")]
            )
        ),
        listing_checker=active_links,
    )
    config = {"configurable": {"thread_id": "test"}}
    return [graph.invoke({"message": message}, config=config) for message in messages]


class AgentTest(unittest.TestCase):
    def test_model_can_call_every_tool(self):
        model = ScriptedModel(AIMessage(content="你好，请告诉我你的租房要求。"))
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "你好")

        self.assertEqual(
            [tool["function"]["name"] for tool in model.tools],
            [
                "search_listings",
                "explore_budgets",
                "get_listing_details",
                "explain_listing",
                "compare_listings",
                "shortlist",
                "exclude_listings",
            ],
        )
        self.assertEqual(result["response"], "你好，请告诉我你的租房要求。")

    def test_view_words_do_not_force_a_details_route(self):
        model = ScriptedModel(
            tool_calls(("compare_listings", {"listing_ids": ["S010", "S009"]})),
            lambda messages: AIMessage(
                content=f"{json.loads(messages[-1].content)['listings'][0]['listing_id']} 综合排名更靠前。"
            ),
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "帮我看看 S010 和 S009 哪个好")

        observation = json.loads(result["observations"][0])
        self.assertEqual(result["trace"][0], '[tool] compare_listings({"listing_ids": ["S010", "S009"]})')
        self.assertTrue(result["trace"][1].startswith("[links] "))
        self.assertEqual(sorted(result["shown_listing_ids"]), ["S009", "S010"])
        self.assertEqual(min(observation["rent_above_cheapest_sgd"].values()), 0)
        self.assertIn("综合排名更靠前", result["response"])

    def test_one_turn_can_shortlist_and_show_another_listing(self):
        model = ScriptedModel(
            tool_calls(
                ("shortlist", {"add": ["S010"]}),
                ("get_listing_details", {"listing_id": "S009"}),
            ),
            AIMessage(content="已收藏 S010，下面是 S009 的要点。"),
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "把 S010 加入候选，再给我看看 S009 的详情")

        self.assertEqual(result["shortlisted_listing_ids"], ["S010"])
        self.assertEqual(result["viewed_listing_id"], "S009")
        self.assertTrue(result["response"].startswith("候选清单已更新：加入 S010"))
        self.assertIn("下面是 S009 的要点", result["response"])

    def test_invented_figures_or_listings_fall_back_after_one_retry(self):
        for reply, problem in (("S010 月租只要 S$999。", "999"), ("S010 不错，S099 也可以看看。", "S099")):
            model = ScriptedModel(
                tool_calls(("get_listing_details", {"listing_id": "S010"})),
                AIMessage(content=reply),
                AIMessage(content=reply),
            )
            with self.subTest(reply=reply), closing(create_mock_database()) as connection:
                (result,) = run_agent(connection, model, "S010 的详情")
                feedback = model.calls[2][-1]
                self.assertIsInstance(feedback, SystemMessage)
                self.assertIn(problem, feedback.content)
                self.assertTrue(result["response"].startswith("房源详情"))
                self.assertNotIn(reply, result["response"])
                guard = [line.rsplit(" -> ", 1)[1] for line in result["trace"] if line.startswith("[guard]")]
                self.assertEqual(guard, ["retry", "fallback"])

    def test_unsupported_offers_and_wrong_language_fall_back(self):
        cases = (
            ("S010 的详情", "需要我帮你联系房东确认入住吗？", "房源详情"),
            ("show me S010", "S010 的月租是 S$1,280。", "Listing details"),
        )
        for message, reply, draft_start in cases:
            model = ScriptedModel(
                tool_calls(("get_listing_details", {"listing_id": "S010"})),
                AIMessage(content=reply),
                AIMessage(content=reply),
            )
            with self.subTest(reply=reply), closing(create_mock_database()) as connection:
                (result,) = run_agent(connection, model, message)
                self.assertTrue(result["response"].startswith(draft_start))

        honest = "I can't contact the landlord, but S010 is in D05."
        model = ScriptedModel(
            tool_calls(("get_listing_details", {"listing_id": "S010"})),
            AIMessage(content=honest),
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "show me S010")
        self.assertEqual(result["response"], honest)

    def test_saved_changes_must_quote_the_latest_user_message(self):
        search = {"set": {"max_price_sgd": 1300, "district_code": "D05"}}
        model = ScriptedModel(
            tool_calls(("search_listings", {**search, "user_quote": "预算2000"})),
            tool_calls(("search_listings", {**search, "user_quote": "预算1300"})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "预算1300，D05")

        rejected, saved = map(json.loads, result["observations"])
        self.assertIn("user_quote", rejected["error"])
        self.assertEqual(saved["saved_changes"], {"max_price_sgd": 1300, "district_code": "D05"})
        self.assertEqual(result["preferences"].max_price_sgd, 1300)
        self.assertTrue(result["response"].startswith("已保存条件变更"))

    def test_preview_keeps_saved_preferences(self):
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1000}, "user_quote": "预算1000"})),
            AIMessage(content=""),
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500}, "preview": True})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            _, preview = run_agent(connection, model, "预算1000", "如果预算1500呢？")

        self.assertEqual(preview["preferences"].max_price_sgd, 1000)
        self.assertEqual(json.loads(preview["observations"][0])["saved_changes"], {})
        self.assertTrue(preview["response"].startswith("预览（尚未修改你的搜索条件）"))

    def test_unstated_cooking_policy_is_shown_for_confirmation(self):
        # V2 states no cooking policy for any whole unit.
        request = "预算4000，D03，整租，要能做饭"
        model = ScriptedModel(
            tool_calls(
                (
                    "search_listings",
                    {
                        "set": {"max_price_sgd": 4000, "district_code": "D03", "rental_scope": "entire_unit", "cooking_required": True},
                        "user_quote": request,
                    },
                )
            ),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        observation = json.loads(result["observations"][0])
        pending = observation["needs_confirmation"]["listings"]
        blocking = max(
            observation["decision_context"],
            key=lambda row: row["database_matches_without_it"],
        )
        self.assertEqual(observation["strict_matches"]["listings"], [])
        self.assertEqual(len(pending), 3)
        self.assertTrue(all("cooking_required" in item["unknown_conditions"] for item in pending))
        self.assertEqual(blocking["condition"], "cooking_required")
        self.assertEqual(result["shown_listing_ids"], [item["listing_id"] for item in pending])
        self.assertIn("需确认（数据未注明）：做饭政策", result["response"])
        self.assertIn("放开「做饭政策」", result["response"])

    def test_first_search_is_saved_and_empty_results_list_relaxations(self):
        # The cheapest listing that allows cooking is S$800, so S$750 plus about 10% reaches it.
        request = "我的预算是750，我想要能做饭的房子，有什么推荐吗"
        model = ScriptedModel(
            tool_calls(
                (
                    "search_listings",
                    {"set": {"max_price_sgd": 750, "cooking_required": True}, "preview": True, "user_quote": "我的预算是750，我想要能做饭的房子"},
                )
            ),
            AIMessage(content="预算内还没有明确可以做饭的房源，下面几套需要确认。"),
            AIMessage(content="好的。"),
        )
        with closing(create_database()) as connection:
            first, _ = run_agent(connection, model, request, "那先这样")

        observation = json.loads(first["observations"][0])
        self.assertFalse(observation["preview"])
        self.assertEqual(first["preferences"].max_price_sgd, 750)
        self.assertTrue(first["preferences"].cooking_required)
        self.assertEqual(observation["relaxation_suggestions"][0]["suggested"], 825)
        self.assertTrue(first["response"].startswith("已保存条件变更"))
        self.assertIn("将最高预算从 S$750 提高到 S$825", first["response"].split("下面几套需要确认。")[1])
        self.assertIn('"suggested": 825', model.calls[2][0].content)

    def test_food_request_ranks_by_nearby_amenities(self):
        request = "我预算5000，我想要周围能吃饭的地方多一点"
        model = ScriptedModel(
            tool_calls(
                (
                    "search_listings",
                    {"set": {"max_price_sgd": 5000, "ranking_priority": "amenities"}, "user_quote": request},
                )
            ),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        shown = json.loads(result["observations"][0])["strict_matches"]["listings"]
        # Food takes 70%, so the busiest food areas lead even over the cheapest room.
        self.assertEqual([item["listing_id"] for item in shown], ["24970286", "60186053", "500029855"])
        self.assertEqual(shown[0]["nearby_1km"], {"fnb": 1282, "hawker_centres": 8, "healthcare": 15})
        self.assertIn("排序偏好 均衡 → 吃饭方便", result["response"])
        self.assertIn("周边餐饮 70%", result["response"])

    def test_space_request_or_minimum_area_can_start_a_search(self):
        cases = (
            ("我想要空间大一点的房子", {"ranking_priority": "space"}),
            ("我要至少80平米", {"min_area_sqm": 80}),
        )
        for request, changes in cases:
            model = ScriptedModel(
                tool_calls(("search_listings", {"set": changes, "user_quote": request})),
                AIMessage(content=""),
            )
            with self.subTest(request=request), closing(create_database()) as connection:
                (result,) = run_agent(connection, model, request)
                shown = json.loads(result["observations"][0])["strict_matches"]["listings"]
                self.assertEqual(len(shown), 3)
                self.assertEqual(result["preferences"].rental_scope, None)
                self.assertEqual(result["preferences"].max_price_sgd, None)
                self.assertEqual(result["preferences"].min_bedrooms, None)
                self.assertTrue(all(item["area_scope"] in {"floor_reported", "room_reported"} for item in shown))
                self.assertIn("广告", result["response"])
                self.assertNotIn("There are no search criteria", " ".join(result["trace"]))
                if "ranking_priority" in changes:
                    self.assertEqual(result["preferences"].min_area_sqm, None)
                    self.assertIn("空间大小 70%", result["response"])
                else:
                    self.assertTrue(all(item["area_sqm"] >= 80 for item in shown))

    def test_a_second_priority_is_added_to_the_saved_one(self):
        first, second = "我想要空间大一点的房子", "也想要周边餐厅多一点"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"ranking_priority": ["space"]}, "user_quote": first})),
            AIMessage(content=""),
            tool_calls(("search_listings", {"set": {"ranking_priority": ["space", "food_places"]}, "user_quote": second})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            _, result = run_agent(connection, model, first, second)

        self.assertEqual(result["preferences"].ranking_priority, ("space", "food_places"))
        self.assertIn("排序偏好 空间大优先 → 空间大优先、餐饮点优先", result["response"])
        # Without a budget: space and food share 70%, MRT keeps 30%.
        self.assertIn("MRT 30%，空间大小 35%，餐饮点 35%", result["response"])

    def test_a_fixable_tool_error_is_explained_traced_and_retried(self):
        def retry_with_iso_code(messages):
            if "call again with its ISO 4217 code" not in messages[-1].content:
                return AIMessage(content="换算失败。")
            return tool_calls(("search_listings", {"budget": {"amount": 10000, "currency": "TWD"}, "user_quote": "预算一万台币"}))

        conversion = {"original_amount": 10000, "original_currency": "TWD", "rate_to_sgd": "0.042", "rate_date": "2026-10-02", "amount_sgd": 420}
        model = ScriptedModel(
            tool_calls(("search_listings", {"budget": {"amount": 10000, "currency": "NTD"}, "user_quote": "预算一万台币"})),
            retry_with_iso_code,
            AIMessage(content="好的。"),
        )
        refused = UnknownCurrencyError("Exchange-rate service rejected NTD (HTTP 404)")
        with closing(create_mock_database()) as connection, patch("agent.convert_to_sgd", side_effect=[refused, conversion]):
            (result,) = run_agent(connection, model, "预算一万台币")

        self.assertIn("fix the arguments and call it\n  again before answering", model.calls[0][0].content)
        self.assertEqual(result["preferences"].max_price_sgd, 420)
        self.assertTrue(result["trace"][0].startswith(
            '[tool] search_listings({"budget": {"amount": 10000, "currency": "NTD"}, "user_quote": "预算一万台币"}) '
            "-> error: Exchange-rate service rejected NTD (HTTP 404): it is not a currency code"
        ))
        self.assertIn("[fx] 10000 TWD -> S$420 (rate 0.042, 2026-10-02)", result["trace"])
        self.assertTrue(result["response"].startswith("已保存条件变更：每月最高预算 不限 → 420"))

    def test_other_tool_errors_say_what_to_do_next(self):
        model = ScriptedModel(
            tool_calls(
                ("search_listings", {"budget": {"amount": 5000, "currency": "CNY"}, "user_quote": "预算5000人民币"}),
                ("get_listing_details", {"listing_id": "S999"}),
                ("search_listings", {"set": {"max_price_sgd": "cheap"}}),
            ),
            AIMessage(content="抱歉，换算服务暂时不可用，请告诉我新币预算。"),
        )
        outage = CurrencyConversionError("Exchange-rate service is unavailable")
        with closing(create_mock_database()) as connection, patch("agent.convert_to_sgd", side_effect=outage):
            (result,) = run_agent(connection, model, "预算5000人民币")

        errors = [json.loads(observation)["error"] for observation in result["observations"]]
        self.assertIn("ask for the budget in SGD", errors[0])
        self.assertIn("Use a listing_id from shown_listings_in_display_order", errors[1])
        self.assertTrue(errors[2].startswith("The arguments do not match the search_listings schema; fix them and call again."))
        self.assertIsNone(result["preferences"].max_price_sgd)
        self.assertTrue(all(" -> error: " in line for line in result["trace"]))

    def test_echoed_defaults_keep_saved_criteria_and_clear_drops_one(self):
        conversion = {"original_amount": 5000, "original_currency": "CNY", "rate_to_sgd": "0.18", "rate_date": "2026-10-02", "amount_sgd": 900}
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300, "district_code": "D05", "rental_scope": "room"}, "user_quote": "预算1300，D05，合租"})),
            AIMessage(content="好的。"),
            # A real model echoed every field at its default along with the new budget.
            tool_calls(
                (
                    "search_listings",
                    {"set": SearchPreferences().model_dump(mode="json"), "budget": {"amount": 5000, "currency": "RMB"}, "user_quote": "我的预算变成了5000rmb"},
                )
            ),
            AIMessage(content="好的。"),
            tool_calls(("search_listings", {"clear": ["district_code"], "user_quote": "地区不限"})),
            AIMessage(content="好的。"),
        )
        with closing(create_mock_database()) as connection, patch("agent.convert_to_sgd", return_value=conversion) as convert:
            _, budget, any_district = run_agent(connection, model, "预算1300，D05，合租", "我的预算变成了5000rmb", "地区不限")

        convert.assert_called_once_with(5000, "RMB")
        self.assertEqual(
            budget["preferences"],
            SearchPreferences(max_price_sgd=900, district_code="D05", rental_scope="room"),
        )
        self.assertTrue(budget["response"].startswith("已保存条件变更：每月最高预算 1300 → 900\n"))
        self.assertEqual(any_district["preferences"], SearchPreferences(max_price_sgd=900, rental_scope="room"))
        self.assertIn("地区 D05 → 不限", any_district["response"])

    def test_mixed_rental_scopes_are_pointed_out(self):
        request = "预算5000"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 5000}, "user_quote": request})),
            AIMessage(content="这几套离 MRT 都很近。"),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        observation = json.loads(result["observations"][0])
        self.assertEqual(observation["rental_scope_mix"]["shown_scopes"], ["room"])
        self.assertTrue(result["response"].endswith(
            "提示：展示的都是合租房间；数据库里符合条件的整租有 88 套，最低 S$2,000。想只看一种，告诉我要整租还是合租即可。"
        ))
        # The note already asks the question, so the draft does not repeat it.
        self.assertNotIn("rental_scope", observation["missing_refinements"])

    def test_unstated_gender_rule_is_shown_as_needing_confirmation(self):
        request = "我是女生，预算3000，整租"
        model = ScriptedModel(
            tool_calls(
                (
                    "search_listings",
                    {"set": {"max_price_sgd": 3000, "tenant_gender": "female", "rental_scope": "entire_unit"}, "user_quote": request},
                )
            ),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        observation = json.loads(result["observations"][0])
        self.assertEqual(observation["strict_matches"]["database_count"], 0)
        self.assertTrue(all(item["unknown_conditions"] == ["tenant_gender"] for item in observation["needs_confirmation"]["listings"]))
        self.assertIn("租客性别 不限 → 女性", result["response"])
        self.assertIn("需确认（数据未注明）：租客性别限制", result["response"])
        self.assertIn("放开「租客性别限制」", result["response"])

    def test_listing_details_report_the_nearby_counts(self):
        model = ScriptedModel(
            tool_calls(("get_listing_details", {"listing_id": "24970286"})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, "看看 24970286")

        self.assertIn("周边（直线 1 公里内）：餐饮 1282 处、小贩中心 8 个", result["response"])
        self.assertIn("最近学校步行 280 米", result["response"])

    def test_whole_unit_request_uses_rental_scope(self):
        request = "我想要整租的，预算5000"
        model = ScriptedModel(
            tool_calls(
                (
                    "search_listings",
                    {"set": {"max_price_sgd": 5000, "rental_scope": "entire_unit"}, "user_quote": request},
                )
            ),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        observation = json.loads(result["observations"][0])
        shown = observation["strict_matches"]["listings"]
        self.assertTrue(shown)
        self.assertEqual({item["rental_scope"] for item in shown}, {"entire_unit"})
        self.assertIn("出租方式 不限 → 整租", result["response"])

    def test_explain_listing_quotes_the_source_text(self):
        model = ScriptedModel(
            tool_calls(("explain_listing", {"listing_id": "500253628"})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, "为什么推荐 500253628？")

        observation = json.loads(result["observations"][0])
        self.assertIn("card_text", observation["evidence"])
        self.assertIn("原文：", result["response"])

    def test_exclude_and_restore_change_later_searches(self):
        search = ("search_listings", {"set": {"max_price_sgd": 1300, "district_code": "D05"}, "user_quote": "预算1300 D05"})
        model = ScriptedModel(
            tool_calls(search),
            AIMessage(content=""),
            tool_calls(("exclude_listings", {"exclude": ["S001"]}), ("search_listings", {})),
            AIMessage(content=""),
            tool_calls(("exclude_listings", {"restore": ["S001"]}), ("search_listings", {})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            first, excluded, restored = run_agent(
                connection, model, "预算1300 D05", "不要 S001 了，再找找", "还是把 S001 加回来"
            )

        self.assertIn("S001", first["shown_listing_ids"])
        self.assertNotIn("S001", excluded["shown_listing_ids"])
        self.assertIn("已排除房源 S001", excluded["response"])
        self.assertIn("S001", restored["shown_listing_ids"])

    def test_foreign_budget_is_converted_before_saving(self):
        conversion = {
            "original_amount": 5_000,
            "original_currency": "CNY",
            "rate_to_sgd": "0.18",
            "rate_date": "2026-09-15",
            "amount_sgd": 900,
        }
        model = ScriptedModel(
            tool_calls(
                (
                    "search_listings",
                    {"budget": {"amount": 5000, "currency": "CNY"}, "user_quote": "预算5000人民币"},
                )
            ),
            AIMessage(content=""),
        )
        with patch("agent.convert_to_sgd", return_value=conversion) as convert, closing(
            create_mock_database()
        ) as connection:
            (result,) = run_agent(connection, model, "预算5000人民币")

        convert.assert_called_once_with(5_000, "CNY")
        self.assertEqual(result["preferences"].max_price_sgd, 900)
        self.assertIn("预算换算：5,000 CNY × 0.18 = S$900", result["response"])

    def test_a_yearly_budget_becomes_a_monthly_limit(self):
        request = "我一年的预算是30万人民币，想要整租"
        conversion = {
            "original_amount": 300_000,
            "original_currency": "CNY",
            "rate_to_sgd": "0.19094",
            "rate_date": "2026-10-05",
            "amount_sgd": 57_282,
        }
        model = ScriptedModel(
            tool_calls(
                (
                    "search_listings",
                    {
                        "set": {"rental_scope": "entire_unit"},
                        "budget": {"amount": 300000, "currency": "CNY", "months": 12},
                        "user_quote": request,
                    },
                )
            ),
            AIMessage(content=""),
        )
        with patch("agent.convert_to_sgd", return_value=conversion) as convert, closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        convert.assert_called_once_with(300_000, "CNY")
        # 300,000 CNY is S$57,282 a year, not a month.
        self.assertEqual(result["preferences"].max_price_sgd, 4_773)
        self.assertIn(
            "预算换算：12 个月共 300,000 CNY × 0.19094 = S$57,282（汇率日期 2026-10-05），÷ 12 = 每月 S$4,773。",
            result["response"],
        )
        self.assertIn("[budget] S$57282 for 12 months -> S$4773 a month", result["trace"])
        self.assertIsNone(json.loads(result["observations"][0])["budget_check"])

    def test_a_yearly_sgd_budget_is_divided_without_conversion(self):
        request = "每年预算6万新币"
        model = ScriptedModel(
            tool_calls(("search_listings", {"budget": {"amount": 60000, "currency": "SGD", "months": 12}, "user_quote": request})),
            AIMessage(content=""),
        )
        with patch("agent.convert_to_sgd") as convert, closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        convert.assert_not_called()
        self.assertEqual(result["preferences"].max_price_sgd, 5_000)
        self.assertIn("预算换算：12 个月共 S$60,000，÷ 12 = 每月 S$5,000。搜索使用 S$5,000 作为月租上限。", result["response"])

    def test_a_monthly_limit_above_most_rents_asks_about_the_period(self):
        # The model kept a yearly-sized amount as monthly; the system asks instead of trusting it.
        first, second = "预算30000新币", "改成1300"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 30000}, "user_quote": first})),
            AIMessage(content=""),
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": second})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            high, low = run_agent(connection, model, first, second)

        self.assertEqual(
            json.loads(high["observations"][0])["budget_check"],
            {"monthly_limit_sgd": 30000, "rent_90th_percentile_sgd": 3800},
        )
        self.assertIn("提醒：每月 S$30,000 的上限高于数据中 90% 房源的月租（S$3,800）", high["response"])
        self.assertNotIn("提醒：每月", low["response"])

    def test_a_budget_far_below_every_rent_is_not_used(self):
        # 一年30rmb is S$0 a month: 万 was most likely left out, so the system asks instead of searching with it.
        request = "预算一年30rmb，希望整租"
        tiny = {"original_amount": 30, "original_currency": "CNY", "rate_to_sgd": "0.19094", "rate_date": "2026-10-05", "amount_sgd": 5}
        model = ScriptedModel(
            tool_calls((
                "search_listings",
                {"set": {"rental_scope": "entire_unit"}, "budget": {"amount": 30, "currency": "CNY", "months": 12}, "user_quote": request},
            )),
            AIMessage(content=""),
        )
        only_budget = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 13}, "user_quote": "预算13"})),
            AIMessage(content="请告诉我正确的金额。"),
        )
        with patch("agent.convert_to_sgd", return_value=tiny), closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, request)
            (stopped,) = run_agent(connection, only_budget, "预算13")

        self.assertIsNone(result["preferences"].max_price_sgd)
        self.assertEqual(result["preferences"].rental_scope, "entire_unit")
        self.assertIsNone(result.get("budget_statement"))
        self.assertEqual(
            json.loads(result["observations"][0])["budget_check"],
            {"monthly_limit_sgd": 0, "lowest_rent_sgd": 850, "stated_budget": {"amount": 30, "currency": "CNY", "months": 12}},
        )
        self.assertTrue(result["response"].startswith(
            "提醒：你说的预算是一年 30 CNY，折合每月 S$0，远低于数据中最便宜房源的月租（S$850），所以这次没有按预算筛选，也没有保存。"
            "如果少写了“万”“千”等单位，请告诉我正确的金额。"
        ))
        self.assertNotIn("预算换算", result["response"])
        # Without another criterion there is nothing to search, but the system still says why.
        self.assertIsNone(stopped["preferences"].max_price_sgd)
        self.assertTrue(stopped["response"].startswith("提醒：每月 S$13 的上限远低于数据中最便宜房源的月租（S$850）"))
        self.assertIn("far below every rent", stopped["observations"][0])

    def test_a_resumed_conversation_drops_delisted_shortlist_entries(self):
        memory = MemorySaver(
            serde=JsonPlusSerializer(allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation")])
        )
        config = {"configurable": {"thread_id": "resume"}}
        first = ScriptedModel(tool_calls(("shortlist", {"add": ["S001", "S010"]})), AIMessage(content="已收藏。"))
        later = ScriptedModel(AIMessage(content="候选清单里还有 S001。"))
        with closing(create_mock_database()) as before, closing(create_mock_database()) as after:
            build_agent(before, first, memory, listing_checker=active_links).invoke({"message": "收藏 S001 和 S010"}, config=config)
            # A data refresh delisted S010 before the user came back.
            after.execute("PRAGMA foreign_keys = OFF")
            after.execute("DELETE FROM listings WHERE listing_id = 'S010'")
            result = build_agent(after, later, memory, listing_checker=active_links).invoke({"message": "我的候选清单还在吗"}, config=config)

        self.assertEqual(result["shortlisted_listing_ids"], ["S001"])
        self.assertTrue(result["response"].startswith("候选清单里的 S010 已不在当前房源数据中（可能已下架），已从候选清单移除。"))
        self.assertIn("[resume] dropped delisted shortlist entries: S010", result["trace"])

    def test_a_conversation_resumed_on_a_later_day_drops_stale_suggestions(self):
        request = "预算800，11月1日入住"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 800, "move_in_date": "2026-11-01"}, "user_quote": request})),
            AIMessage(content=""),
            AIMessage(content="好的，有需要再告诉我。"),
        )
        memory = MemorySaver(
            serde=JsonPlusSerializer(allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation")])
        )
        config = {"configurable": {"thread_id": "later-day"}}
        with closing(create_mock_database()) as connection:
            graph = build_agent(connection, model, memory, listing_checker=active_links)
            first = graph.invoke({"message": request}, config=config)
            with patch("agent.date") as clock:
                clock.today.return_value = date(2026, 11, 2)
                later = graph.invoke({"message": "我回来了"}, config=config)

        # Nothing within S$800, so the first turn suggested a higher budget.
        self.assertEqual(first["relaxations"][0]["suggested"], 880)
        self.assertEqual(later["relaxations"], [])
        self.assertIsNone(later["last_search"])
        self.assertEqual(later["last_active_date"], "2026-11-02")
        self.assertEqual(later["preferences"].max_price_sgd, 800)
        self.assertTrue(later["response"].startswith("你之前填写的入住日期 2026-11-01 已经过去，如需更新请告诉我。"))

    def test_consent_is_asked_once_and_allow_keeps_criteria_with_the_users_words(self):
        profiles = UserProfiles(memory_storage())
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300, "rental_scope": "room"}, "user_quote": "预算1300，合租"})),
            AIMessage(content=""),
            tool_calls(("user_memory", {"action": "allow", "user_quote": "记住吧"})),
            AIMessage(content="好的。"),
            tool_calls(("shortlist", {"add": ["S001"]})),
            AIMessage(content="已收藏。"),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            asked = say(graph, "first", "预算1300，合租")
            self.assertIsNone(profiles.profile("alice"))
            allowed = say(graph, "first", "记住吧")
            later = say(graph, "first", "收藏 S001")

        self.assertIn("user_memory", [tool["function"]["name"] for tool in model.tools])
        self.assertTrue(asked["response"].endswith("要我记住这些条件吗？记住后，下次开新对话时我会先问你是否沿用；随时可以说“忘掉我的信息”删除。"))
        self.assertTrue(allowed["response"].startswith("好的，已记住当前的条件、候选和排除。"))
        self.assertNotIn("要我记住", later["response"])
        kept = profiles.profile("alice")
        self.assertEqual(kept["preferences"], {"max_price_sgd": 1300, "rental_scope": "room"})
        self.assertEqual(kept["sources"]["max_price_sgd"]["quote"], "预算1300，合租")
        self.assertEqual(kept["shortlisted_listing_ids"], ["S001"])
        # Long-term memory keeps saved criteria only, never the conversation itself.
        self.assertNotIn("messages", kept)

    def test_a_new_conversation_offers_the_kept_profile_and_reuses_it_at_todays_rate(self):
        profiles = UserProfiles(memory_storage())
        profiles.set_consent("alice", True)
        profiles.save("alice", {
            "preferences": {"max_price_sgd": 4773, "rental_scope": "room"},
            "budget": {"amount": 300000, "currency": "CNY", "months": 12},
            "sources": {"max_price_sgd": {"quote": "一年30万人民币", "date": "2026-10-05"}},
            "shortlisted_listing_ids": ["S001", "S999"],
            "excluded_listing_ids": ["S002"],
            "response_language": "zh",
            "saved_on": "2026-10-05",
        })
        today = {"original_amount": 300000, "original_currency": "CNY", "rate_to_sgd": "0.2", "rate_date": "2026-11-01", "amount_sgd": 60000}
        model = ScriptedModel(
            AIMessage(content="你好！"),
            tool_calls(("user_memory", {"action": "restore", "user_quote": "沿用"}), ("search_listings", {})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection, patch("agent.convert_to_sgd", return_value=today) as convert:
            graph = memory_agent(connection, model, profiles)
            offered = say(graph, "second", "你好")
            reused = say(graph, "second", "沿用")

        self.assertTrue(offered["response"].startswith(
            "欢迎回来。上次（2026-10-05）记住的条件：预算 一年 300,000 CNY；出租方式 合租/单间；候选清单 2 套（S999 已不在当前房源数据中）。"
        ))
        self.assertEqual(offered["preferences"], SearchPreferences())
        convert.assert_called_once_with(300000, "CNY")
        self.assertEqual(reused["preferences"], SearchPreferences(max_price_sgd=5000, rental_scope="room"))
        self.assertEqual(reused["shortlisted_listing_ids"], ["S001"])
        self.assertEqual(reused["excluded_listing_ids"], ["S002"])
        self.assertIn("÷ 12 = 每月 S$5,000", reused["response"])
        self.assertIn("已沿用上次的候选清单：S001；S999 已不在当前房源数据中，未恢复。", reused["response"])
        # The restored criteria are kept again at today's rate.
        self.assertEqual(profiles.profile("alice")["preferences"]["max_price_sgd"], 5000)

    def test_an_offered_profile_is_kept_until_new_criteria_replace_it(self):
        profiles = UserProfiles(memory_storage())
        profiles.set_consent("alice", True)
        earlier = {"preferences": {"max_price_sgd": 1300}, "shortlisted_listing_ids": ["S002"], "saved_on": "2026-10-05"}
        profiles.save("alice", earlier)
        model = ScriptedModel(
            tool_calls(("shortlist", {"add": ["S001"]})),
            AIMessage(content="已收藏。"),
            tool_calls(("search_listings", {"set": {"max_price_sgd": 2000}, "user_quote": "预算2000"})),
            AIMessage(content=""),
            tool_calls(("user_memory", {"action": "forget", "user_quote": "忘掉我的信息"})),
            AIMessage(content="已删除。"),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            say(graph, "third", "收藏 S001")
            self.assertEqual(profiles.profile("alice"), earlier)
            say(graph, "third", "预算2000")
            self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 2000})
            forgotten = say(graph, "third", "忘掉我的信息")

        self.assertIsNone(profiles.profile("alice"))
        self.assertFalse(profiles.consent("alice"))
        self.assertTrue(forgotten["response"].startswith("已删除为你长期保存的条件、候选和排除，之后也不会再保存。"))

    def test_the_faculty_is_saved_from_the_users_answer_and_used_for_commutes(self):
        profiles = UserProfiles(memory_storage())
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500, "max_commute_minutes": 30}, "user_quote": "预算1500，到学校30分钟以内"})),
            AIMessage(content="你在哪个学院？"),
            tool_calls(("faculty", {"action": "set", "faculty": "计算机学院", "user_quote": "计算机学院"}), ("search_listings", {})),
            AIMessage(content=""),
            tool_calls(("faculty", {"action": "commute", "faculty": "Faculty of Law", "listing_ids": ["S006"]})),
            AIMessage(content=""),
            tool_calls(("faculty", {"action": "commute", "faculty": "商学院", "listing_ids": ["S006", "S010"]})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            first = say(graph, "t", "预算1500，到学校30分钟以内")
            second = say(graph, "t", "计算机学院")
            third = say(graph, "t", "如果我在法学院，S006 要多久")
            fourth = say(graph, "t", "去商学院呢")

        # Without a faculty the commute condition cannot be checked, and the system says why.
        self.assertIn("还没有设置你的学院，所以通勤时间没法计算", first["response"])
        self.assertEqual(json.loads(first["observations"][0])["strict_matches"]["database_count"], 0)
        self.assertTrue(second["response"].startswith("已把你的学院设为计算机学院，之后所有对话都按它计算通勤时间。"))
        self.assertEqual(profiles.faculty("alice"), "School of Computing")
        strict = json.loads(second["observations"][1])["strict_matches"]["listings"]
        self.assertEqual({row["listing_id"] for row in strict}, {"S006", "S010"})
        self.assertEqual({row["commute_minutes_to_faculty"] for row in strict}, {25, 28})
        self.assertIn("到计算机学院：公共交通约 25 分钟（工作日 8:30 出发）", second["response"])
        # Another faculty is only looked up: the fixture has no minutes to it, and nothing is saved.
        self.assertIn("没有这套房到法学院的通勤数据", third["response"])
        self.assertEqual(json.loads(third["observations"][0])["saved_faculty"], "School of Computing")
        self.assertEqual(profiles.faculty("alice"), "School of Computing")
        # Within 1.5 km walking can be the faster way, and the reply says so.
        self.assertIn("S006）：步行约 9 分钟", fourth["response"])
        self.assertEqual(json.loads(fourth["observations"][0])["listings"][0]["commute_mode"], "walk")

    def test_a_faculty_changed_on_the_settings_page_applies_from_the_next_message(self):
        profiles = UserProfiles(memory_storage())
        profiles.set_consent("alice", True)
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500, "ranking_priority": "commute"}, "user_quote": "预算1500，通勤近一点"})),
            AIMessage(content=""),
            tool_calls(("search_listings", {})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            before = say(graph, "t", "预算1500，通勤近一点")
            profiles.set_faculty("alice", "School of Computing")
            after = say(graph, "t", "再看看")

        self.assertIsNone(before["preferences"].faculty)
        self.assertEqual(after["preferences"].faculty, "School of Computing")
        self.assertEqual(json.loads(after["observations"][0])["strict_matches"]["listings"][0]["listing_id"], "S006")
        self.assertIn('"faculty": "School of Computing"', model.calls[2][0].content)
        # The faculty is an account setting, never one of the kept criteria.
        self.assertNotIn("faculty", profiles.profile("alice")["preferences"])

    def test_saving_a_faculty_needs_the_users_words_and_a_recorded_faculty(self):
        profiles = UserProfiles(memory_storage())
        model = ScriptedModel(
            tool_calls(
                ("faculty", {"action": "set", "faculty": "School of Computing"}),
                ("faculty", {"action": "set", "faculty": "Yale-NUS", "user_quote": "Yale-NUS"}),
                ("faculty", {"action": "commute"}),
            ),
            AIMessage(content="请问你在哪个学院？"),
        )
        with closing(create_mock_database()) as connection:
            result = say(memory_agent(connection, model, profiles), "t", "我是 Yale-NUS 的")

        errors = [json.loads(observation).get("error", "") for observation in result["observations"]]
        self.assertIn("user_quote", errors[0])
        self.assertIn("not a recorded faculty", errors[1])
        self.assertIn("No faculty is saved", errors[2])
        self.assertIsNone(profiles.faculty("alice"))

    def test_earlier_tool_traffic_is_not_resent_to_the_model(self):
        model = ScriptedModel(
            tool_calls(("shortlist", {"add": ["S001"]})),
            AIMessage(content="已收藏。"),
            AIMessage(content="候选清单里有 1 套。"),
        )
        with closing(create_mock_database()) as connection:
            _, second = run_agent(connection, model, "收藏 S001", "我收藏了几套？")

        sent = model.calls[2]
        self.assertEqual(
            [type(message).__name__ for message in sent],
            ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"],
        )
        self.assertIn('"listing_id": "S001"', sent[0].content)
        self.assertEqual(second["response"], "候选清单里有 1 套。")

    def test_tool_rounds_are_capped(self):
        model = ScriptedModel(*[tool_calls(("shortlist", {})) for _ in range(10)])
        with closing(create_mock_database()) as connection:
            graph = build_agent(connection, model, listing_checker=active_links, max_tool_rounds=2)
            result = graph.invoke({"message": "看看候选清单"})

        self.assertEqual(len(model.calls), 3)
        self.assertEqual(len(result["trace"]), 2)
        self.assertIn("候选清单目前是空的", result["response"])

    def test_openai_responses_api_round_trip(self):
        requests = []

        def openai_api(request):
            body = json.loads(request.content)
            requests.append((request.url.path, body))
            if len(requests) == 1:
                arguments = {"set": {"max_price_sgd": 1300, "district_code": "D05"}, "user_quote": "预算1300，D05"}
                output = [
                    {"type": "reasoning", "id": "rs_1", "summary": []},
                    {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "search_listings", "arguments": json.dumps(arguments), "status": "completed"},
                ]
            else:
                observation = json.loads(body["input"][-1]["output"])
                first = observation["strict_matches"]["listings"][0]
                text = f"第一套是 {first['listing_id']}，月租 S${first['rent_monthly_sgd']}。"
                output = [
                    {"type": "reasoning", "id": "rs_2", "summary": []},
                    {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]},
                ]
            return httpx.Response(
                200,
                json={
                    "id": f"resp_{len(requests)}",
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "model": "gpt-5.6-luna",
                    "output": output,
                    "parallel_tool_calls": True,
                    "tool_choice": "auto",
                    "tools": [],
                },
            )

        model = ChatOpenAI(
            model="gpt-5.6-luna",
            api_key="test-key",
            use_responses_api=True,
            max_retries=0,
            http_socket_options=(),
            http_client=httpx.Client(transport=httpx.MockTransport(openai_api)),
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "预算1300，D05")

        (_, first), (_, second) = requests
        self.assertEqual({path for path, _ in requests}, {"/v1/responses"})
        self.assertNotIn("reasoning_effort", first)
        self.assertEqual(
            [item.get("type") for item in second["input"][-3:]],
            ["reasoning", "function_call", "function_call_output"],
        )
        self.assertTrue(result["response"].endswith("第一套是 S010，月租 S$1280。"))

    def test_rejected_reply_is_retried_and_left_out_of_history(self):
        model = ScriptedModel(
            AIMessage(content="S099 很适合你。"),
            AIMessage(content="你好，请告诉我预算或想住的地区。"),
            AIMessage(content="好的，请告诉我预算。"),
        )
        with closing(create_mock_database()) as connection:
            first, _ = run_agent(connection, model, "你好", "我还没想好")

        self.assertEqual(first["response"], "你好，请告诉我预算或想住的地区。")
        self.assertIn("S099", model.calls[1][-1].content)
        self.assertNotIn("S099", " ".join(str(message.content) for message in model.calls[2]))
        self.assertEqual(
            [type(message).__name__ for message in model.calls[2]],
            ["SystemMessage", "HumanMessage", "AIMessage", "HumanMessage"],
        )

    def test_second_rejection_without_tools_shows_saved_state(self):
        search = {"set": {"max_price_sgd": 1300, "district_code": "D05"}, "user_quote": "预算1300 D05"}
        model = ScriptedModel(
            tool_calls(("search_listings", search)),
            AIMessage(content=""),
            AIMessage(content="预算提高到 S$1,800 会更好。"),
            AIMessage(content="预算提高到 S$1,800 会更好。"),
        )
        with closing(create_mock_database()) as connection:
            _, result = run_agent(connection, model, "预算1300 D05", "怎么样更好")

        self.assertTrue(result["response"].startswith("抱歉，我没能可靠地回答这个问题。"))
        self.assertIn("当前保存的条件：每月最高预算 1300；地区 D05", result["response"])
        self.assertIn("上次展示的房源：1. ", result["response"])

    def test_budget_question_without_a_number_explores_without_saving(self):
        request = "预算1300，D23，要能做饭"
        question = "我可以进一步提高我的预算，还有更好的选择吗"

        def reply_from_ladder(messages):
            observation = json.loads(messages[-1].content)
            rung = next(level for level in observation["levels"] if level["max_price_sgd"] == 1500)
            pending = rung["needs_confirmation"]
            return AIMessage(
                content=(
                    "提高预算不会多出明确能做饭的房源。"
                    f"预算到 S$1,500：{pending['count']} 套需确认，其中 {pending['mrt_within_10_min']} 套步行 10 分钟内到 MRT。"
                    "你更看重离地铁近，还是整租？"
                )
            )

        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300, "district_code": "D23", "cooking_required": True}, "user_quote": request})),
            AIMessage(content=""),
            tool_calls(("explore_budgets", {})),
            reply_from_ladder,
        )
        with closing(create_database()) as connection:
            _, result = run_agent(connection, model, request, question)

        observation = json.loads(result["observations"][0])
        self.assertIn('"last_saved_search"', model.calls[2][0].content)
        self.assertEqual([level["max_price_sgd"] for level in observation["levels"]], [1300, 1500, 2000, 3000, None])
        self.assertFalse(observation["strict_matches_grow_with_budget"])
        self.assertEqual(result["preferences"].max_price_sgd, 1300)
        self.assertTrue(result["response"].startswith("提高预算不会多出明确能做饭的房源。"))
        self.assertEqual(len(result["trace"]), 1)

    def test_budget_levels_without_a_saved_budget_start_from_the_lowest_level(self):
        model = ScriptedModel(
            tool_calls(("explore_budgets", {"budgets": [1300, 1000]})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "预算 1000 和 1300 分别有多少房源")

        observation = json.loads(result["observations"][0])
        self.assertEqual([level["max_price_sgd"] for level in observation["levels"]], [1000, 1300, None])
        self.assertTrue(observation["strict_matches_grow_with_budget"])
        self.assertTrue(result["response"].startswith("不同预算下的房源数量"))

    def test_apartment_request_filters_property_types(self):
        request = "我想要公寓，预算3000"
        apartments = ["condominium", "executive_condominium", "apartment", "walk_up_apartment"]
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 3000, "property_types": apartments}, "user_quote": request})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)

        shown = json.loads(result["observations"][0])["strict_matches"]["listings"]
        self.assertTrue(shown)
        self.assertTrue({item["property_type"] for item in shown} <= set(apartments))
        self.assertIn("物业类型 不限 → condominium、executive_condominium、apartment、walk_up_apartment", result["response"])

    def test_unverified_links_keep_their_rank_and_are_explained(self):
        def checker(listing_id, url):
            if listing_id == "S010":
                return {"status": "inactive", "final_url": url, "http_status": 404, "error_reason": "http_404"}
            if listing_id == "S001":
                return {"status": "unknown", "final_url": None, "http_status": 403, "error_reason": "http_403"}
            return {"status": "active", "final_url": url, "http_status": 200}

        note = "网站返回 HTTP 403，因此暂时无法确认链接是否仍然有效；这不表示房源已下架"
        search = {"set": {"max_price_sgd": 1300, "district_code": "D05"}, "user_quote": "预算1300 D05"}
        for reply in ("S004 更便宜，S001 链接暂时无法确认。", ""):
            model = ScriptedModel(tool_calls(("search_listings", search)), AIMessage(content=reply))
            with self.subTest(reply=reply), closing(create_mock_database()) as connection:
                connection.execute("DELETE FROM listing_health")
                graph = build_agent(connection, model, listing_checker=checker)
                result = graph.invoke({"message": "预算1300 D05"})
                health = connection.execute(
                    "SELECT status, error_reason FROM listing_health WHERE listing_id = 'S001'"
                ).fetchone()

                facts = json.loads(result["observations"][0])["strict_matches"]["listings"]
                # S001 is nearer MRT than S004, so it keeps first place with an unverified link.
                self.assertEqual(result["shown_listing_ids"], ["S001", "S004"])
                self.assertEqual(health, ("unknown", "http_403"))
                self.assertEqual(facts[0]["link_note"], note)
                self.assertIn("[links] S001 unknown (http_403); S004 active; 1 inactive skipped", result["trace"])
                self.assertEqual(result["response"].count(note), 1)
                if reply:
                    self.assertTrue(result["response"].endswith(f"链接检查：\n- Synthetic Clementi Common Room（S001）：{note}。"))

    def test_model_failure_after_a_tool_returns_the_draft(self):
        def unavailable(_):
            raise RuntimeError("model unavailable")

        model = ScriptedModel(
            tool_calls(("get_listing_details", {"listing_id": "S010"})),
            unavailable,
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "S010 的详情")

        self.assertTrue(result["response"].startswith("房源详情"))


if __name__ == "__main__":
    unittest.main()
