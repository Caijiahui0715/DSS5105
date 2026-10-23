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

import tempfile
from pathlib import Path

from agent import build_agent, opening_state, save_to_profile
from mock_db import DEFAULT_FIXTURE, create_database, create_mock_database, empty_storage, set_listing
from exchange import CurrencyConversionError, UnknownCurrencyError
from models import SearchPreferences
from onemap import OneMapError
from profiles import UserProfiles, merged
from sessions import STATE_MODULES
from tools import get_listings_by_ids, rank_listings


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
        MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation"), ("models", "Destination")])),
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
                allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation"), ("models", "Destination")]
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
                "estimate_costs",
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

    def test_a_comparison_is_a_table_in_the_chosen_order_and_the_table_is_pointed_out_once(self):
        profiles = UserProfiles(empty_storage())
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "预算1300"})),
            AIMessage(content=""),
            tool_calls(("compare_listings", {"listing_ids": ["S010", "S009", "S003"]})),
            AIMessage(content="S010 离 MRT 更近，S009 更便宜。"),
            tool_calls(("compare_listings", {"listing_ids": ["S010", "S009"]})),
            AIMessage(content="差别不大。"),
            tool_calls(("compare_listings", {"listing_ids": ["S001", "S002", "S003", "S004"]})),
            AIMessage(content="一次最多比较三套，你想比较哪三套？"),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            say(graph, "first", "预算1300")
            first = say(graph, "first", "比较 S010、S009 和 S003")
            again = say(graph, "second", "比较 S010 和 S009")
            many = say(graph, "second", "比较 S001 到 S004")

        view = first["comparison"]
        self.assertEqual(view["listing_ids"], ["S010", "S009", "S003"])
        self.assertEqual(first["shown_listing_ids"], ["S010", "S009", "S003"])
        self.assertEqual(first["last_comparison"], view)
        rows = {row["label"]["zh"]: row["values"] for row in view["rows"]}
        self.assertEqual(rows["月租"]["S009"], {"zh": "S$1,250（最便宜）", "en": "S$1,250 (cheapest)"})
        self.assertEqual(rows["月租"]["S003"]["zh"], "S$1,700（比最便宜的贵 S$450）")
        self.assertEqual(rows["是否符合条件（按比较时的条件）"]["S003"]["zh"], "不符合：预算")
        self.assertEqual(rows["链接"]["S010"]["zh"], "有效")
        self.assertEqual(view["summary"]["zh"], "S009 最便宜（S$1,250）；S010 离 MRT 最近（约 4 分钟）；S003 不符合当前条件")
        # The system points to the table the first time only, before the model's analysis.
        self.assertTrue(first["response"].startswith("对比表在右侧“比较”栏，点开就能看到。\n\nS010 离 MRT 更近"))
        self.assertEqual(again["response"], "差别不大。")
        self.assertEqual(again["comparison"]["listing_ids"], ["S010", "S009"])
        # More than three: nothing compared, the model asks which three.
        self.assertIn("At most three", json.loads(many["observations"][0])["error"])
        self.assertIsNone(many["comparison"])
        self.assertEqual(many["last_comparison"]["listing_ids"], ["S010", "S009"])

    def test_listings_left_out_of_a_comparison_are_named(self):
        def links(listing_id, url):
            if listing_id == "S009":
                return {"status": "inactive", "final_url": url, "http_status": 404, "error_reason": "http_404"}
            return active_links(listing_id, url)

        model = ScriptedModel(
            tool_calls(("compare_listings", {"listing_ids": ["S010", "S009", "S003"]})),
            AIMessage(content="S010 更便宜。"),
            tool_calls(("compare_listings", {"listing_ids": ["S010", "S009", "NOPE"]})),
            AIMessage(content="请再选一套。"),
        )
        with closing(create_mock_database()) as connection:
            # No cached link checks, so the checker decides.
            connection.run("DELETE FROM listing_health")
            graph = build_agent(connection, model, MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation"), ("models", "Destination")])), listing_checker=links)
            config = {"configurable": {"thread_id": "left-out"}}
            two = graph.invoke({"message": "比较 S010、S009 和 S003"}, config=config)
            one = graph.invoke({"message": "比较 S010、S009 和 NOPE"}, config=config)

        self.assertEqual(two["comparison"]["listing_ids"], ["S010", "S003"])
        self.assertTrue(two["response"].startswith("S009 的原链接已失效，没有加入比较。"))
        # One listing left: not compared; the table keeps it so the page can ask for another.
        self.assertEqual(one["comparison"]["listing_ids"], ["S010"])
        self.assertEqual(json.loads(one["observations"][0])["left_out"], {"S009": "inactive", "NOPE": "missing"})
        self.assertTrue(one["response"].startswith("S009 的原链接已失效，没有加入比较。 NOPE 不在当前房源数据中，没有加入比较。"))

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
        self.assertTrue(result["response"].startswith("已更新本次对话的条件"))

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
        self.assertTrue(first["response"].startswith("已更新本次对话的条件"))
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
        self.assertEqual([item["listing_id"] for item in shown], ["24970286", "24203641", "60186053"])
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
        self.assertTrue(result["response"].startswith("已更新本次对话的条件：每月最高预算 不限 → S$420"))

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
        self.assertTrue(budget["response"].startswith("已更新本次对话的条件：每月最高预算 S$1,300 → S$900\n"))
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
            "提示：展示的都是合租房间；数据库里符合条件的整租有 115 套，最低 S$1,350。想只看一种，告诉我要整租还是合租即可。"
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
            tool_calls(("explain_listing", {"listing_id": "12059415"})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, "为什么推荐 12059415？")

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

    def test_a_criterion_both_set_and_cleared_takes_the_new_value(self):
        # From a real conversation: the model "replaced" the saved budget and ranking by also naming
        # them in clear. 60000 SDG (Sudanese pounds, a typo for SGD) a year is S$10 a month.
        first = "预算1300，通勤短一点"
        again = "I change my budget to 60000 SDG per year, again, I want some apartments with short commute time"
        sudanese = {"original_amount": 60000, "original_currency": "SDG", "rate_to_sgd": "0.00214", "rate_date": "2026-10-11", "amount_sgd": 128}
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300, "ranking_priority": ["commute"]}, "user_quote": first})),
            AIMessage(content=""),
            tool_calls(("search_listings", {
                "set": {"property_types": ["apartment"], "ranking_priority": ["commute"]},
                "clear": ["max_price_sgd", "ranking_priority"],
                "budget": {"amount": 60000, "currency": "SDG", "months": 12},
                "user_quote": again,
            })),
            AIMessage(content=""),
        )
        with patch("agent.convert_to_sgd", return_value=sudanese), closing(create_mock_database()) as connection:
            _, result = run_agent(connection, model, first, again)

        self.assertEqual(result["preferences"].ranking_priority, ("commute",))
        self.assertEqual(list(result["preferences"].property_types), ["apartment"])
        # The stated budget was far below every rent, so it was not used and the saved one stays.
        self.assertEqual(result["preferences"].max_price_sgd, 1300)

    def test_several_people_search_whole_units_with_a_bedroom_each(self):
        # From a real conversation: no whole unit states how many may live there, so 三个人住 used to
        # leave nothing strict and the model added a space priority of its own.
        request = "预算6500，要三个人住"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 6500, "occupant_count": 3}, "user_quote": request})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)
            shown = get_listings_by_ids(connection, result["shown_listing_ids"])

        preferences = result["preferences"]
        self.assertEqual((preferences.rental_scope, preferences.min_bedrooms, preferences.ranking_priority), ("entire_unit", 3, ()))
        self.assertIn("出租方式 不限 → 整租", result["response"])
        self.assertIn("按整套、一人一间找了至少 3 个卧室。如果有人合住一间，告诉我一共需要几个卧室。", result["response"])
        self.assertTrue(shown)
        self.assertTrue(all(listing["rental_scope"] == "entire_unit" and listing["bedrooms"] >= 3 for listing in shown))
        self.assertEqual({card["status"] for card in result["recommendations"]["listings"]}, {"match"})
        self.assertIn("How many people will live there\n  is occupant_count, not a wish for space.", model.calls[0][0].content)

    def test_a_room_search_for_several_people_turns_to_whole_units(self):
        first, second = "想合租，预算6500", "我们三个人住"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"rental_scope": "room", "max_price_sgd": 6500}, "user_quote": first})),
            AIMessage(content=""),
            tool_calls(("search_listings", {"set": {"occupant_count": 3}, "user_quote": second})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            _, result = run_agent(connection, model, first, second)

        self.assertEqual((result["preferences"].rental_scope, result["preferences"].min_bedrooms), ("entire_unit", 3))
        self.assertIn("出租方式 合租/单间 → 整租", result["response"])
        self.assertIn("系统找不到几个人合住的单间，所以按整租找。按整套、一人一间找了至少 3 个卧室。", result["response"])

    def test_two_people_renting_one_room_see_rooms_to_confirm(self):
        request = "想合租，预算2000，我和女朋友两个人住一间"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"rental_scope": "room", "max_price_sgd": 2000, "occupant_count": 2}, "user_quote": request})),
            AIMessage(content=""),
        )
        with closing(create_database()) as connection:
            (result,) = run_agent(connection, model, request)
            pax = {listing["listing_id"]: listing["tenant_count_reported"] for listing in get_listings_by_ids(connection, result["shown_listing_ids"])}

        self.assertEqual((result["preferences"].rental_scope, result["preferences"].min_bedrooms), ("room", None))
        self.assertIn("按两人合住一个单间找。如果是想各住一间，系统找不到同一套里的两个单间，可以改找 2 房的整租。", result["response"])
        cards = result["recommendations"]["listings"]
        self.assertTrue(cards)
        # A room's "N pax" label is only a clue, so every room needs confirming, except that a room
        # advertised for one person is left out.
        for card in cards:
            self.assertEqual(card["status"], "needs_confirmation")
            self.assertNotEqual(pax[card["listing_id"]], 1)
            if pax[card["listing_id"]]:
                self.assertIn(f"广告标注 {pax[card['listing_id']]} pax，能住几个人要问房东", "；".join(card["unknown_condition_labels"]))
        # Relaxing the budget or the MRT walk cannot settle an unstated occupancy.
        self.assertNotIn("单项小幅放宽后也暂未找到", result["response"])

    def test_bedrooms_set_from_the_number_of_people_follow_it(self):
        turns = [
            ("最少两个卧室，预算6500", {"min_bedrooms": 2, "max_price_sgd": 6500}),
            ("我们三个人住", {"occupant_count": 3}),
            ("改成两个人", {"occupant_count": 2}),
            ("就我一个人住了", {"occupant_count": 1}),
        ]
        steps = []
        for message, values in turns:
            steps += [tool_calls(("search_listings", {"set": values, "user_quote": message})), AIMessage(content="")]
        with closing(create_database()) as connection:
            results = run_agent(connection, ScriptedModel(*steps), *(message for message, _ in turns))

        self.assertEqual([result["preferences"].min_bedrooms for result in results], [2, 3, 2, None])
        self.assertIn("按整套、一人一间找了至少 3 个卧室（原来是至少 2 个）。", results[1]["response"])
        self.assertIn("最少卧室数 3 → 2", results[2]["response"])
        self.assertEqual(results[3]["preferences"].rental_scope, "entire_unit")
        self.assertIn("按一个人住找，按人数设的卧室数也去掉了，仍然只找整租。要不要也看看单间？", results[3]["response"])

    def test_bold_text_ending_in_punctuation_still_renders(self):
        model = ScriptedModel(AIMessage(content="**主要取舍：**先告诉我你的预算。"))
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "你好")

        self.assertIn("**主要取舍**：先告诉我你的预算。", result["response"])

    def test_a_resumed_conversation_drops_delisted_shortlist_entries(self):
        memory = MemorySaver(
            serde=JsonPlusSerializer(allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation"), ("models", "Destination")])
        )
        config = {"configurable": {"thread_id": "resume"}}
        first = ScriptedModel(tool_calls(("shortlist", {"add": ["S001", "S010"]})), AIMessage(content="已收藏。"))
        later = ScriptedModel(AIMessage(content="候选清单里还有 S001。"))
        with closing(create_mock_database()) as before, closing(create_mock_database()) as after:
            build_agent(before, first, memory, listing_checker=active_links).invoke({"message": "收藏 S001 和 S010"}, config=config)
            # A data refresh delisted S010 before the user came back.
            after.run("DELETE FROM listings WHERE listing_id = 'S010'")
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
            serde=JsonPlusSerializer(allowed_msgpack_modules=[("models", "SearchPreferences"), ("models", "NearbyLocation"), ("models", "Destination")])
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

    def test_auto_save_saves_criteria_as_they_change_until_switched_off(self):
        profiles = UserProfiles(empty_storage())
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 2500}, "user_quote": "预算2500"})),
            AIMessage(content=""),
            tool_calls(("user_memory", {"action": "auto_on", "user_quote": "打开自动保存"})),
            AIMessage(content="好的。"),
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1800}, "user_quote": "预算改成1800"})),
            AIMessage(content=""),
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500}, "preview": True})),
            AIMessage(content=""),
            tool_calls(("estimate_costs", {"lease_months": 6, "rent": {"amount": 1800}, "user_quote": "租6个月"})),
            AIMessage(content=""),
            tool_calls(("user_memory", {"action": "auto_off", "user_quote": "关闭自动保存"})),
            AIMessage(content="好的。"),
            tool_calls(("search_listings", {"set": {"district_code": "D05"}, "user_quote": "只看D05"})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            first = say(graph, "auto", "预算2500")
            self.assertIn("已更新本次对话的条件：", first["response"])
            self.assertNotIn("长期资料吗", first["response"])
            self.assertIsNone(profiles.profile("alice"))
            switched = say(graph, "auto", "打开自动保存")
            # Switching it on switches an undecided memory on and saves what changed so far.
            self.assertTrue(profiles.consent("alice") and profiles.auto_save("alice"))
            self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 2500})
            changed = say(graph, "auto", "预算改成1800")
            self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 1800})
            self.assertEqual(profiles.profile("alice")["sources"]["max_price_sgd"]["quote"], "预算改成1800")
            # A preview is never saved.
            say(graph, "auto", "如果预算1500呢")
            self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 1800})
            costs = say(graph, "auto", "租6个月")
            self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 1800, "lease_months": 6})
            off = say(graph, "auto", "关闭自动保存")
            later = say(graph, "auto", "只看D05")

        self.assertTrue(switched["response"].startswith(
            "已开启自动保存和长期记忆：之后对话里改的条件会自动存进长期资料。刚才的 1 项改动已存：每月最高预算 不限 → S$2,500。"
            "想停止，在个人资料页关掉“自动保存”，或者在对话里说“关闭自动保存”。"
        ))
        self.assertIn("已更新本次对话的条件，并自动存到长期资料：每月最高预算 S$2,500 → S$1,800", changed["response"])
        self.assertIn("已更新本次对话的条件，并自动存到长期资料：签约租期（月） 不限 → 6", costs["response"])
        self.assertTrue(off["response"].startswith("已关闭自动保存："))
        self.assertFalse(profiles.auto_save("alice"))
        # Off: a change stays in the conversation.
        self.assertIn("已更新本次对话的条件：地区 不限 → D05", later["response"])
        self.assertNotIn("district_code", profiles.profile("alice")["preferences"])
        self.assertIn('"auto_save": false', model.calls[-1][0].content)

    def test_auto_save_waits_while_memory_is_off(self):
        profiles = UserProfiles(empty_storage())
        profiles.set_auto_save("alice", True)
        profiles.set_consent("alice", False)
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1800}, "user_quote": "预算1800"})),
            AIMessage(content=""),
            tool_calls(("user_memory", {"action": "on", "user_quote": "打开长期记忆"})),
            AIMessage(content="好的。"),
            tool_calls(("search_listings", {"set": {"rental_scope": "room"}, "user_quote": "合租"})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            paused = say(graph, "paused", "预算1800")
            self.assertIsNone(profiles.profile("alice"))
            on = say(graph, "paused", "打开长期记忆")
            resumed = say(graph, "paused", "合租")

        self.assertIn("已更新本次对话的条件：每月最高预算", paused["response"])
        self.assertIn("自动保存继续", on["response"])
        self.assertIn("并自动存到长期资料：出租方式 不限 → 合租/单间", resumed["response"])
        # Everything this conversation changed since it started is saved, as saving by hand would.
        self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 1800, "rental_scope": "room"})

    def test_criteria_are_saved_only_when_asked_with_the_users_words(self):
        profiles = UserProfiles(empty_storage())
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300, "rental_scope": "room"}, "user_quote": "预算1300，合租"})),
            AIMessage(content=""),
            tool_calls(("user_memory", {"action": "save", "user_quote": "存吧"})),
            AIMessage(content="好的。"),
            tool_calls(("search_listings", {"set": {"district_code": "D05"}, "user_quote": "只看D05"}), ("shortlist", {"add": ["S001"]})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            asked = say(graph, "first", "预算1300，合租")
            self.assertIsNone(profiles.profile("alice"))
            self.assertIsNone(profiles.consent("alice"))
            saved = say(graph, "first", "存吧")
            later = say(graph, "first", "只看D05，收藏 S001")

        self.assertIn("user_memory", [tool["function"]["name"] for tool in model.tools])
        # Nothing asks whether to save; the page offers automatic saving.
        self.assertNotIn("长期资料吗", asked["response"])
        # Saving switches memory on for a user who never decided, and says what changed.
        self.assertTrue(saved["response"].startswith(
            "已存到长期资料：每月最高预算 不限 → S$1,300；出租方式 不限 → 合租/单间。之后的新对话会按这些条件开始。长期记忆已打开。"
        ))
        self.assertTrue(profiles.consent("alice"))
        # A later change stays in the conversation until it is saved.
        kept = profiles.profile("alice")
        self.assertEqual(kept["preferences"], {"max_price_sgd": 1300, "rental_scope": "room"})
        self.assertEqual(kept["sources"]["max_price_sgd"]["quote"], "预算1300，合租")
        self.assertEqual(json.loads(later["observations"][0])["preferences"]["district_code"], "D05")
        self.assertIn('"unsaved_profile_changes": ["district_code"]', model.calls[-1][0].content)
        # The shortlist is the account's, not part of the long-term profile; conversation text never is.
        self.assertEqual(profiles.listings("alice"), (["S001"], []))
        self.assertEqual(set(kept), {"preferences", "sources", "budget", "saved_on"})

    def test_a_new_conversation_starts_from_the_long_term_profile_at_todays_rate(self):
        profiles = UserProfiles(empty_storage())
        profiles.save("alice", {
            "preferences": {"max_price_sgd": 4773, "rental_scope": "room"},
            "budget": {"amount": 300000, "currency": "CNY", "months": 12},
            "sources": {"max_price_sgd": {"quote": "一年30万人民币", "date": "2026-10-05"}},
            "saved_on": "2026-10-05",
        })
        today = {"original_amount": 300000, "original_currency": "CNY", "rate_to_sgd": "0.2", "rate_date": "2026-11-01", "amount_sgd": 60000}
        model = ScriptedModel(tool_calls(("search_listings", {})), AIMessage(content=""))
        config = {"configurable": {"thread_id": "second"}}
        with closing(create_mock_database()) as connection, patch("agent.convert_to_sgd", return_value=today) as convert:
            graph = memory_agent(connection, model, profiles)
            opening = opening_state(profiles, "alice", "zh")
            graph.update_state(config, opening, as_node="finalize")
            started = say(graph, "second", "开始找")

        convert.assert_called_once_with(300000, "CNY")
        first = opening["messages"][0]
        self.assertTrue(first.content.startswith("已按你的长期资料设好条件：每月最高预算 S$5,000；出租方式 合租/单间。"))
        self.assertIn("÷ 12 = 每月 S$5,000", first.content)
        self.assertEqual(opening["reply_traces"][first.id], ["[memory] started from the long-term profile saved on 2026-10-05"])
        self.assertEqual(started["preferences"], SearchPreferences(max_price_sgd=5000, rental_scope="room"))
        # The opening is part of the conversation the model sees.
        self.assertIn(first.content, [message.content for message in model.calls[0]])
        # Starting from the profile is no change to save.
        self.assertIn('"unsaved_profile_changes": []', model.calls[0][0].content)

    def test_saving_keeps_what_the_page_changed_meanwhile_and_drops_cleared_criteria(self):
        profiles = UserProfiles(empty_storage())
        profiles.save("alice", {"preferences": {"max_price_sgd": 1300, "rental_scope": "room"}, "saved_on": "2026-10-05"})
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"district_code": "D05"}, "user_quote": "只看D05"})),
            AIMessage(content=""),
            tool_calls(("user_memory", {"action": "save", "user_quote": "存到我的资料"})),
            AIMessage(content="已保存。"),
            tool_calls(("search_listings", {"clear": ["district_code"], "user_quote": "区域不限"}), ("user_memory", {"action": "save", "user_quote": "区域不限，也存一下"})),
            AIMessage(content="已保存。"),
        )
        config = {"configurable": {"thread_id": "third"}}
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            graph.update_state(config, opening_state(profiles, "alice", "zh"), as_node="finalize")
            say(graph, "third", "只看D05")
            # Meanwhile the Profile page raises the budget.
            page = merged(profiles.profile("alice"), {"max_price_sgd": 3000}, {"max_price_sgd": {"via": "profile", "date": "2026-10-19"}}, None)
            profiles.save("alice", page)
            saved = say(graph, "third", "存到我的资料")
            self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 3000, "rental_scope": "room", "district_code": "D05"})
            cleared = say(graph, "third", "区域不限，也存一下")

        self.assertTrue(saved["response"].startswith("已存到长期资料：地区 不限 → D05。"))
        self.assertNotIn("长期记忆已打开", saved["response"])
        kept = profiles.profile("alice")
        self.assertEqual(kept["preferences"], {"max_price_sgd": 3000, "rental_scope": "room"})
        self.assertEqual(kept["sources"], {"max_price_sgd": {"via": "profile", "date": "2026-10-19"}})
        self.assertIn("已存到长期资料：地区 D05 → 不限。", cleared["response"])

    def test_memory_off_pauses_the_profile_and_saving_asks_to_switch_it_on(self):
        profiles = UserProfiles(empty_storage())
        profiles.save("alice", {"preferences": {"max_price_sgd": 1300}, "saved_on": "2026-10-05"})
        profiles.set_consent("alice", False)
        model = ScriptedModel(
            tool_calls(
                ("search_listings", {"set": {"max_price_sgd": 1500}, "user_quote": "预算1500，存到我的资料"}),
                ("user_memory", {"action": "save", "user_quote": "存到我的资料"}),
            ),
            AIMessage(content="长期记忆已关闭，要打开并保存吗？"),
            tool_calls(("user_memory", {"action": "save", "switch_on": True, "user_quote": "要"})),
            AIMessage(content="好的。"),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            # Off: what is kept stays, but a new conversation does not start from it.
            self.assertIsNone(opening_state(profiles, "alice", "zh"))
            asked = say(graph, "fourth", "预算1500，存到我的资料")
            self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 1300})
            saved = say(graph, "fourth", "要")

        self.assertIn("长期记忆已关闭，要打开并保存吗？", json.loads(asked["observations"][1])["error"])
        self.assertTrue(profiles.consent("alice"))
        self.assertEqual(profiles.profile("alice")["preferences"], {"max_price_sgd": 1500})
        self.assertIn("长期记忆已打开。", saved["response"])

    def test_forget_deletes_the_criteria_and_switches_memory_off_but_keeps_listings(self):
        profiles = UserProfiles(empty_storage())
        profiles.save("alice", {"preferences": {"max_price_sgd": 1300}, "saved_on": "2026-10-05"})
        profiles.set_auto_save("alice", True)
        model = ScriptedModel(
            tool_calls(("shortlist", {"add": ["S001"]}), ("exclude_listings", {"exclude": ["S002"]})),
            AIMessage(content="好的。"),
            tool_calls(("user_memory", {"action": "forget", "user_quote": "忘掉我的信息"})),
            AIMessage(content="已删除。"),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            say(graph, "fifth", "收藏 S001，不要 S002")
            forgotten = say(graph, "fifth", "忘掉我的信息")

        self.assertIsNone(profiles.profile("alice"))
        self.assertFalse(profiles.consent("alice"))
        self.assertEqual(profiles.listings("alice"), (["S001"], ["S002"]))
        self.assertTrue(forgotten["response"].startswith("已删除长期资料里的条件，长期记忆现在关着。收藏和排除的房源不受影响。自动保存也关了。"))
        self.assertFalse(profiles.auto_save("alice"))

    def test_the_shortlist_is_shared_and_shortlisted_matches_are_named_after_the_results(self):
        profiles = UserProfiles(empty_storage())
        model = ScriptedModel(
            tool_calls(("shortlist", {"add": ["S006"]})),
            AIMessage(content="已收藏。"),
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1400, "district_code": "D05"}, "user_quote": "预算1400，D05"})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            graph = memory_agent(connection, model, profiles)
            say(graph, "one", "收藏 S006")
            found = say(graph, "two", "预算1400，D05")

        # Another conversation of the same account sees the shortlist.
        self.assertEqual(found["shortlisted_listing_ids"], ["S006"])
        observation = json.loads(found["observations"][0])
        self.assertEqual(observation["shortlisted_also_matching"], ["S006"])
        self.assertNotIn("S006", [row["listing_id"] for row in observation["strict_matches"]["listings"]])
        self.assertIn("另外，你收藏的 S006 也符合这次的全部条件", found["response"])

    def test_the_faculty_is_saved_from_the_users_answer_and_used_for_commutes(self):
        profiles = UserProfiles(empty_storage())
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
        profiles = UserProfiles(empty_storage())
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
        save_to_profile(profiles, "alice", after)
        self.assertNotIn("faculty", profiles.profile("alice")["preferences"])

    def test_saving_a_faculty_needs_the_users_words_and_a_recorded_faculty(self):
        profiles = UserProfiles(empty_storage())
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
                connection.run("DELETE FROM listing_health")
                graph = build_agent(connection, model, listing_checker=checker)
                result = graph.invoke({"message": "预算1300 D05"})
                (health,) = connection.query(
                    "SELECT status, error_reason FROM listing_health WHERE listing_id = 'S001'"
                )

                facts = json.loads(result["observations"][0])["strict_matches"]["listings"]
                # S001 is nearer MRT than S004, so it keeps first place with an unverified link.
                self.assertEqual(result["shown_listing_ids"], ["S001", "S004"])
                self.assertEqual(health, {"status": "unknown", "error_reason": "http_403"})
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



class CostAndLeaseTest(unittest.TestCase):
    @staticmethod
    def lease(connection, terms):
        for listing_id, term in terms.items():
            set_listing(connection, listing_id, lease_term=term)

    def test_costs_use_the_listings_lease_and_are_shown_word_for_word(self):
        model = ScriptedModel(
            tool_calls(("estimate_costs", {"listing_ids": ["S001"]})),
            AIMessage(content="签约时要先付 S$3,715。"),
        )
        with closing(create_mock_database()) as connection:
            self.lease(connection, {"S001": "2 years"})
            (result,) = run_agent(connection, model, "S001 一共要花多少钱")

        estimate = json.loads(result["observations"][0])["estimates"][0]
        # S$1,200 a month for 24 months: S$28,800 rent, S$115 stamp duty, two months' deposit.
        self.assertEqual(
            (estimate["lease_months"], estimate["stamp_duty_sgd"], estimate["deposit_sgd"], estimate["upfront_sgd"]),
            (24, 115, 2400, 3715),
        )
        self.assertTrue(result["response"].startswith(
            "费用估算：Synthetic Clementi Common Room（S001）\n假设：租期 24 个月（房源要求至少签 2 年）"
        ))
        self.assertTrue(result["response"].endswith("签约时要先付 S$3,715。"))
        self.assertEqual(result["viewed_listing_id"], "S001")

    def test_a_stated_lease_is_saved_and_a_longer_listing_term_wins(self):
        request = "我只租 5 个月，帮我算 S001"
        model = ScriptedModel(
            tool_calls(("estimate_costs", {"listing_ids": ["S001"], "lease_months": 5, "user_quote": "我只租 5 个月"})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            self.lease(connection, {"S001": "1 year"})
            (result,) = run_agent(connection, model, request)

        self.assertEqual(result["preferences"].lease_months, 5)
        self.assertEqual(result["preference_sources"]["lease_months"]["quote"], "我只租 5 个月")
        response = result["response"]
        self.assertTrue(response.startswith("已更新本次对话的条件：签约租期（月） 不限 → 5\n\n提示：新加坡规定私人住宅最短租期 3 个月"))
        self.assertIn("租期 12 个月（这套房源要求至少签 1 年，比你说的 5 个月更长）", response)
        self.assertTrue(response.endswith("费用明细见上。"))

    def test_this_one_among_several_shown_listings_is_asked_about(self):
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "预算1300"})),
            AIMessage(content="找到几套。"),
            tool_calls(("estimate_costs", {})),
            AIMessage(content="你想算哪一套？"),
        )
        with closing(create_mock_database()) as connection:
            _, result = run_agent(connection, model, "预算1300", "算一下这套的费用")

        self.assertIn("ask the user which listing they mean", result["observations"][0])
        self.assertEqual(result["response"], "你想算哪一套？")

    def test_a_listing_opened_before_a_new_search_is_not_assumed(self):
        model = ScriptedModel(
            tool_calls(("get_listing_details", {"listing_id": "S003"})),
            AIMessage(content=""),
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "预算1300"})),
            AIMessage(content=""),
            tool_calls(("estimate_costs", {})),
            AIMessage(content="你想算哪一套？"),
        )
        with closing(create_mock_database()) as connection:
            *_, result = run_agent(connection, model, "看看 S003", "预算1300", "这套要花多少")

        self.assertIn("ask the user which listing they mean", result["observations"][0])

    def test_nothing_to_cost_is_asked_about(self):
        model = ScriptedModel(tool_calls(("estimate_costs", {})), AIMessage(content="你想算哪一套，或者月租是多少？"))
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "租房要花多少钱")

        self.assertIn("no listing or rent to work from", result["observations"][0])

    def test_agent_and_deposit_answers_are_kept_for_the_conversation(self):
        quote = "我找了中介，押金一个月"
        model = ScriptedModel(
            tool_calls(("estimate_costs", {"listing_ids": ["S001"], "uses_agent": True, "deposit_months": 1, "user_quote": quote})),
            AIMessage(content=""),
            tool_calls(("estimate_costs", {"listing_ids": ["S002"]})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            self.lease(connection, {"S001": "1 year", "S002": "1 year"})
            _, second = run_agent(connection, model, f"{quote}，S001 要多少钱", "那 S002 呢")

        estimate = json.loads(second["observations"][0])["estimates"][0]
        # Half a month's rent for a one-year lease, plus 9% GST.
        self.assertEqual((estimate["deposit_months"], estimate["agent_fee_sgd"], estimate["agent_fee_gst_sgd"]), (1, 525, 47.25))
        self.assertEqual(second["cost_assumptions"], {"uses_agent": True, "deposit_months": 1})
        self.assertIn("押金 1 个月（按你说的）；包含中介费（按惯例估算）", second["response"])

    def test_stated_values_need_the_users_words(self):
        model = ScriptedModel(
            tool_calls(("estimate_costs", {"listing_ids": ["S001"], "uses_agent": True})),
            AIMessage(content="你有找中介吗？"),
        )
        with closing(create_mock_database()) as connection:
            (result,) = run_agent(connection, model, "S001 要多少钱")

        self.assertIn("user_quote", result["observations"][0])
        self.assertEqual(result.get("cost_assumptions"), {})

    def test_a_rent_in_another_currency_is_converted_first(self):
        conversion = {"original_amount": 5000, "original_currency": "CNY", "rate_to_sgd": "0.18", "rate_date": "2026-10-02", "amount_sgd": 900}
        model = ScriptedModel(tool_calls(("estimate_costs", {"rent": {"amount": 5000, "currency": "CNY"}})), AIMessage(content=""))
        with closing(create_mock_database()) as connection, patch("agent.convert_to_sgd", return_value=conversion):
            (result,) = run_agent(connection, model, "月租 5000 人民币要先付多少")

        lines = result["response"].splitlines()
        self.assertEqual(lines[0], "月租换算：5,000 CNY × 0.18 = S$900（汇率日期 2026-10-02）。")
        self.assertEqual(lines[1], "费用估算：按你给的月租")
        self.assertIn("- 月租：S$900（按你说的）", lines)
        self.assertIn("- 签约时预付：押金 S$900 + 第一个月租金 S$900 + 印花税 S$43 = S$1,843", lines)

    def test_a_short_lease_search_mentions_the_legal_minimums(self):
        request = "只租2个月，预算1300"
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"lease_months": 2, "max_price_sgd": 1300}, "user_quote": request})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            self.lease(connection, {"S001": "Flexible", "S002": "1 year"})
            (result,) = run_agent(connection, model, request)

        strict = json.loads(result["observations"][0])["strict_matches"]["listings"]
        self.assertEqual([(item["listing_id"], item["lease_term"]) for item in strict], [("S001", "Flexible")])
        self.assertNotIn("S002", result["shown_listing_ids"])
        self.assertIn("提示：新加坡规定私人住宅最短租期 3 个月", result["response"])
        self.assertIn("   租期：灵活", result["response"])


def two_faculty_database():
    """The made-up listings with trips to NUS Business School too, a roommate's faculty."""
    data = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
    business = {"S001": 20, "S003": 12, "S004": 15, "S010": 40, "S011": 22}
    for row in data["listings"]:
        if row["listing_id"] in business:
            row["commutes"]["NUS Business School"] = {"minutes": business[row["listing_id"]], "mode": "transit"}
    path = Path(tempfile.mkdtemp()) / "listings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return create_mock_database(path)


class FakeRoutes:
    """Routes to a place by listing: minutes, None for no route, or "fail" for a OneMap error."""

    def __init__(self, minutes):
        self.minutes, self.calls = minutes, []

    def __call__(self, listing, destination):
        self.calls.append(listing["listing_id"])
        minutes = self.minutes.get(listing["listing_id"])
        if minutes == "fail":
            raise OneMapError("OneMap /api/public/routingsvc/route failed: HTTP 502.")
        return None if minutes is None else {"minutes": minutes, "mode": "transit"}


class OtherDestinationTest(unittest.TestCase):
    """Besides the user's faculty, one more place the commute must suit."""

    def agent(self, connection, model, profiles, routes=None):
        return build_agent(connection, model, MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_MODULES)),
                           listing_checker=active_links, profiles=profiles, place_router=routes or FakeRoutes({}))

    def test_a_roommates_faculty_has_its_own_limit_shows_everywhere_and_can_be_kept(self):
        profiles = UserProfiles(empty_storage())
        profiles.set_faculty("alice", "School of Computing")
        profiles.set_consent("alice", True)
        quote = "预算1500，我在计算机学院，室友在商学院，两边都30分钟以内"
        destination = {"query": "NUS Business School", "name": "室友的学院"}
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500, "max_commute_minutes": 30, "other_destination": destination,
                                                    "max_other_commute_minutes": 30}, "user_quote": quote})),
            AIMessage(content=""),
            tool_calls(("compare_listings", {"listing_ids": ["S006", "S010"]})),
            AIMessage(content=""),
            tool_calls(("search_listings", {"clear": ["other_destination"], "user_quote": "不用管室友了"})),
            AIMessage(content=""),
        )
        with closing(two_faculty_database()) as connection:
            graph = self.agent(connection, model, profiles)
            first = say(graph, "t", quote)
            save_to_profile(profiles, "alice", first)
            second = say(graph, "t", "比较 S006 和 S010")
            third = say(graph, "t", "不用管室友了")
            opening = opening_state(profiles, "alice", "zh")

        observation = json.loads(first["observations"][0])
        # S010 is 28 minutes from SoC but 40 from the Business School.
        self.assertEqual([row["listing_id"] for row in observation["strict_matches"]["listings"]], ["S006"])
        self.assertNotIn("S010", [row["listing_id"] for row in observation["needs_confirmation"]["listings"]])
        self.assertEqual(observation["strict_matches"]["listings"][0]["other_commute"]["minutes"], 9)
        self.assertEqual(first["preferences"].other_destination.faculty, "NUS Business School")
        self.assertIn("另一个通勤目的地 不限 → 室友的学院（商学院）", first["response"])
        self.assertIn("到计算机学院：公共交通约 25 分钟", first["response"])
        self.assertIn("到室友的学院（商学院）：步行约 9 分钟", first["response"])
        # The comparison table has a row for it, and the key differences name the quicker one.
        rows = {row["label"]["zh"]: row["values"] for row in second["comparison"]["rows"]}
        self.assertEqual(rows["到室友的学院（商学院）通勤"]["S010"]["zh"], "公共交通约 40 分钟")
        self.assertIn("S006 到室友的学院（商学院）最快（约 9 分钟）", second["comparison"]["summary"]["zh"])
        # Kept in the long-term profile, a new conversation starts with it.
        self.assertIn("另一个通勤目的地 室友的学院（商学院）", opening["messages"][0].content)
        self.assertEqual(opening["preferences"].other_destination.faculty, "NUS Business School")
        # Dropping it drops its limit too.
        self.assertIsNone(third["preferences"].other_destination)
        self.assertIsNone(third["preferences"].max_other_commute_minutes)

    def test_commute_ranking_counts_the_longer_trip(self):
        with closing(two_faculty_database()) as connection:
            listings = get_listings_by_ids(connection, ["S001", "S010"])
        preferences = SearchPreferences(
            ranking_priority=("commute",), faculty="School of Computing",
            other_destination={"query": "NUS Business School", "faculty": "NUS Business School", "latitude": 1.2933, "longitude": 103.7741},
        )
        ranked = {item["listing"]["listing_id"]: item for item in rank_listings(listings, preferences)}
        # S001: 35 to SoC, 20 to the Business School; S010: 28 and 40.
        self.assertEqual(ranked["S001"]["factors"]["commute"]["ratio"], round(35 / 45, 3))
        self.assertEqual(ranked["S010"]["factors"]["commute"]["ratio"], round(40 / 45, 3))

    def test_a_new_place_replaces_the_other_destination_only_once_the_user_agrees_and_its_routes_are_worked_out(self):
        profiles = UserProfiles(empty_storage())
        profiles.set_faculty("alice", "School of Computing")
        gym = {"query": "Tiong Bahru Plaza", "name": "健身房"}
        change = {"set": {"other_destination": gym, "ranking_priority": ["commute"]}}
        routes = FakeRoutes({"S001": 18, "S004": None, "S006": 12, "S010": "fail"})
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500, "other_destination": {"query": "NUS Business School", "name": "室友的学院"},
                                                    "max_other_commute_minutes": 30}, "user_quote": "预算1500，室友在商学院，30分钟以内"})),
            AIMessage(content=""),
            tool_calls(("search_listings", {**change, "user_quote": "健身房"})),
            AIMessage(content="要换吗？"),
            tool_calls(("search_listings", {**change, "replace_destination": True, "user_quote": "好"})),
            AIMessage(content="要等吗？"),
            tool_calls(("search_listings", {**change, "replace_destination": True, "wait_for_routes": True, "user_quote": "可以等"})),
            AIMessage(content=""),
            tool_calls(("search_listings", {})),
            AIMessage(content=""),
        )
        with closing(two_faculty_database()) as connection:
            # S003 has a position too, but is over the budget even 10% higher; S011's data is flagged.
            for listing_id, position in {"S001": (1.31, 103.76), "S003": (1.30, 103.78), "S004": (1.28, 103.79), "S006": (1.311, 103.765),
                                         "S010": (1.312, 103.766), "S011": (1.30, 103.75)}.items():
                set_listing(connection, listing_id, latitude=position[0], longitude=position[1])
            graph = self.agent(connection, model, profiles, routes)
            with patch("tools.geocode_location", return_value=(1.2865, 103.8270)), patch("place_routes.ASK_ABOVE", 2):
                say(graph, "t", "预算1500，室友在商学院，30分钟以内")
                asked = say(graph, "t", "我健身房在 Tiong Bahru Plaza，也要方便")
                agreed = say(graph, "t", "好")
                calls_before_waiting = list(routes.calls)
                worked = say(graph, "t", "可以等")
                again = say(graph, "t", "再看看")
            kept = connection.query("SELECT listing_id, minutes FROM place_routes ORDER BY listing_id")

        error = json.loads(asked["observations"][0])["error"]
        self.assertIn("除了你的学院，最多只能再加一个目的地，现在已经有「室友的学院（商学院）」。要把它换成「健身房（Tiong Bahru Plaza）」吗？", error)
        self.assertEqual(asked["preferences"].other_destination.faculty, "NUS Business School")
        # Agreed, but four listings need routes: asked whether to wait, and nothing is worked out or saved yet.
        self.assertIn("符合其他条件的有 4 套房源", json.loads(agreed["observations"][0])["error"])
        self.assertEqual(calls_before_waiting, [])
        self.assertEqual(agreed["preferences"].other_destination.faculty, "NUS Business School")
        # Only the listings within the budget (10% higher) with a position are worked out.
        self.assertEqual(sorted(routes.calls[:4]), ["S001", "S004", "S006", "S010"])
        self.assertEqual(worked["preferences"].other_destination.query, "Tiong Bahru Plaza")
        self.assertEqual((worked["preferences"].other_destination.latitude, worked["preferences"].other_destination.longitude), (1.2865, 103.8270))
        # The roommate's limit went with the roommate.
        self.assertIsNone(worked["preferences"].max_other_commute_minutes)
        strict = json.loads(worked["observations"][0])["strict_matches"]["listings"]
        self.assertEqual(strict[0]["listing_id"], "S006")
        self.assertIn("到健身房（Tiong Bahru Plaza）：公共交通约 12 分钟", worked["response"])
        self.assertIn("有 1 套房源暂时算不出到「健身房（Tiong Bahru Plaza）」的通勤时间", worked["response"])
        # Kept: the next search asks OneMap only for the one that failed.
        self.assertEqual(routes.calls[4:], ["S010"])
        # S004 has no route: kept as such, it needs confirmation rather than being asked again, as do
        # S010 (failed) and the listings without a position (S002, S005, S009).
        self.assertEqual({row["listing_id"]: row["minutes"] for row in kept}, {"S001": 18, "S004": None, "S006": 12})
        self.assertEqual(json.loads(worked["observations"][0])["needs_confirmation"]["database_count"], 5)
        self.assertIn("S006", [row["listing_id"] for row in json.loads(again["observations"][0])["strict_matches"]["listings"]])

    def test_a_commute_limit_is_suggested_ten_minutes_longer(self):
        profiles = UserProfiles(empty_storage())
        profiles.set_faculty("alice", "School of Computing")
        model = ScriptedModel(
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500, "max_commute_minutes": 20}, "user_quote": "预算1500，到学校20分钟以内"})),
            AIMessage(content=""),
        )
        with closing(create_mock_database()) as connection:
            result = say(self.agent(connection, model, profiles), "t", "预算1500，到学校20分钟以内")

        self.assertIn("将到学院的通勤上限从 20 分钟放宽到 30 分钟", result["response"])
        self.assertEqual([item["suggested"] for item in result["relaxations"] if item["field"] == "max_commute_minutes"], [30])


if __name__ == "__main__":
    unittest.main()
