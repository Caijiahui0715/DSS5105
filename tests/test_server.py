import importlib.util
import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from psycopg import OperationalError

from group_db import UNAVAILABLE
from mock_db import create_mock_database, empty_storage
from profiles import UserProfiles
from sessions import serializer
from tests.test_agent import ScriptedModel, active_links, tool_calls

PASSWORD = "password123"


def events(response):
    """The (name, data) pairs of a Server-Sent Events body."""
    found = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        found.append((fields["event"], json.loads(fields["data"])))
    return found


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "run `uv add fastapi uvicorn` to test the web demo")
class ServerTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from server import create_app

        self.listings = create_mock_database()
        self.model = ScriptedModel()
        self.storage = empty_storage()
        self.checkpointer = MemorySaver(serde=serializer())
        self.app = create_app(self.listings, self.model, self.storage, self.checkpointer, listing_checker=active_links)
        self.client = lambda: TestClient(self.app)
        self.alice, self.bob = self.client(), self.client()

    def tearDown(self):
        self.listings.close()

    def sign_up(self, client, name):
        response = client.post("/api/register", json={"username": name, "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["username"]

    def send(self, client, thread_id, message, *steps, language=None):
        self.model.steps.extend(steps)
        response = client.post(f"/api/conversations/{thread_id}/messages", json={"message": message, "language": language})
        self.assertEqual(response.status_code, 200, response.text)
        return events(response)

    def test_accounts_sign_in_and_out(self):
        self.assertEqual(self.alice.get("/api/me").status_code, 401)
        self.assertEqual(self.sign_up(self.alice, "Alice"), "alice")
        self.assertEqual(self.alice.get("/api/me").json(), {"username": "alice", "faculty": None})

        taken = self.bob.post("/api/register", json={"username": "alice", "password": PASSWORD})
        self.assertEqual((taken.status_code, taken.json()["detail"]), (400, "This username is already taken."))
        wrong = self.bob.post("/api/login", json={"username": "alice", "password": "not-the-password"})
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (400, "Wrong username or password."))
        # Signing in on a second device is a separate session.
        self.assertEqual(self.bob.post("/api/login", json={"username": "ALICE", "password": PASSWORD}).status_code, 200)

        self.alice.post("/api/logout")
        self.assertEqual(self.alice.get("/api/me").status_code, 401)
        self.assertEqual(self.bob.get("/api/me").status_code, 200)

    def test_a_reply_streams_progress_and_stays_in_the_history(self):
        self.sign_up(self.alice, "alice")
        thread_id = self.alice.post("/api/conversations").json()["id"]

        found = self.send(
            self.alice, thread_id, "预算1300",
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "预算1300"})),
            AIMessage(content=""),
        )

        progress = [data["zh"] for name, data in found if name == "progress"]
        self.assertEqual(progress[0], "正在理解你的需求")
        self.assertIn("正在搜索房源", progress)
        name, reply = found[-1]
        self.assertEqual(name, "reply")
        # The criteria change in this conversation only; nothing asks whether to save them.
        self.assertIn("已更新本次对话的条件：每月最高预算 不限 → S$1,300", reply["text"])
        self.assertNotIn("长期资料吗", reply["text"])
        self.assertEqual(reply["sources"]["max_price_sgd"]["quote"], "预算1300")
        self.assertEqual(reply["steps"][0], "搜索房源")
        # The listings the search showed, for the frontend's cards, in display order.
        shown = reply["recommendations"]["listings"]
        self.assertFalse(reply["recommendations"]["preview"])
        self.assertEqual([item["position"] for item in shown], list(range(1, len(shown) + 1)))
        self.assertTrue(all(item["status"] in {"match", "needs_confirmation"} and item["rent_monthly_sgd"] <= 1300 for item in shown))

        history = self.alice.get(f"/api/conversations/{thread_id}/messages").json()
        self.assertEqual(history, [
            {"role": "user", "text": "预算1300"},
            {"role": "assistant", "text": reply["text"], "steps": reply["steps"]},
        ])
        listed = self.alice.get("/api/conversations").json()
        self.assertEqual([(thread["id"], thread["title"]) for thread in listed], [(thread_id, "预算1300")])

    def test_a_frontend_server_signs_in_with_a_header_token(self):
        self.sign_up(self.alice, "alice")
        frontend = self.client()
        wrong = frontend.post("/api/token", json={"username": "alice", "password": "not-the-password"})
        self.assertEqual(wrong.status_code, 400)
        signed_in = frontend.post("/api/token", json={"username": "alice", "password": PASSWORD}).json()
        header = {"Authorization": f"Bearer {signed_in['token']}"}

        self.assertEqual((signed_in["token_type"], signed_in["username"]), ("bearer", "alice"))
        self.assertEqual(frontend.get("/api/me").status_code, 401)
        self.assertEqual(frontend.get("/api/me", headers=header).json()["username"], "alice")
        frontend.post("/api/logout", headers=header)
        self.assertEqual(frontend.get("/api/me", headers=header).status_code, 401)
        # The page's own cookie session is a different token and stays signed in.
        self.assertEqual(self.alice.get("/api/me").status_code, 200)

    def test_listings_can_be_browsed_and_opened_after_signing_in(self):
        self.assertEqual(self.alice.get("/api/listings").status_code, 401)
        # The sign-up form's choices need no account.
        options = self.alice.get("/api/options").json()
        self.assertIn({"code": "D05", "name": "Buona Vista / West Coast / Clementi New Town"}, options["districts"])
        self.assertEqual(options["property_types"], sorted(set(options["property_types"])))
        self.assertIn("condominium", options["property_types"])
        self.sign_up(self.alice, "alice")

        page = self.alice.get("/api/listings?limit=5&offset=10").json()
        details = self.alice.get("/api/listings/S001").json()

        self.assertEqual(page["total"], 12)
        self.assertEqual(len(page["listings"]), 2)
        self.assertEqual(details["listing"]["listing_id"], "S001")
        self.assertIn("commutes", details["listing"])
        self.assertEqual(self.alice.get("/api/listings/NOPE").status_code, 404)

    def test_a_reopened_conversation_has_its_criteria_listings_and_the_accounts_shortlist(self):
        self.sign_up(self.alice, "alice")
        thread_id = self.alice.post("/api/conversations").json()["id"]
        self.assertEqual(
            self.alice.get(f"/api/conversations/{thread_id}").json(),
            {"id": thread_id, "preferences": {}, "sources": {}, "items": [], "profile_changes": [], "recommendations": None, "comparison": None, "shortlist": []},
        )
        # The shortlist is the account's: a favorite saved anywhere shows in every conversation.
        self.assertEqual(self.alice.post("/api/me/shortlist", json={"listing_id": "S002"}).json(), {"shortlist": ["S002"], "excluded": []})
        self.send(
            self.alice, thread_id, "预算1300",
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "预算1300"})),
            AIMessage(content=""),
        )
        shown = self.alice.get(f"/api/conversations/{thread_id}").json()["recommendations"]["listings"]
        # A later turn without a search keeps the listings for the panel.
        name, reply = self.send(self.alice, thread_id, "谢谢", AIMessage(content="不客气！"))[-1]
        self.assertEqual((reply["recommendations"], reply["shortlist"]), (None, ["S002"]))

        snapshot = self.alice.get(f"/api/conversations/{thread_id}").json()
        self.assertEqual(snapshot["preferences"], {"max_price_sgd": 1300})
        self.assertEqual(snapshot["sources"]["max_price_sgd"]["quote"], "预算1300")
        self.assertEqual(snapshot["items"][0]["label"]["zh"], "每月最高预算")
        self.assertEqual(snapshot["items"][0]["value"], {"zh": "S$1,300", "en": "S$1,300"})
        self.assertEqual(snapshot["recommendations"]["listings"], shown)
        first = shown[0]["listing_id"]
        self.assertEqual(self.alice.post("/api/me/shortlist", json={"listing_id": first}).json()["shortlist"], ["S002", first])
        self.assertEqual(self.alice.delete("/api/me/shortlist/S002").json()["shortlist"], [first])
        self.assertEqual(self.alice.post("/api/me/shortlist", json={"listing_id": "NOPE"}).status_code, 404)
        other = self.alice.post("/api/conversations").json()["id"]
        self.assertEqual(self.alice.get(f"/api/conversations/{other}").json()["shortlist"], [first])
        self.assertEqual(self.alice.get("/api/me/listings").json(), {"shortlist": [first], "excluded": []})
        self.assertEqual(self.bob.get(f"/api/conversations/{thread_id}").status_code, 401)

    def test_an_excluded_listing_is_restored_on_the_page(self):
        self.sign_up(self.alice, "alice")
        thread_id = self.alice.post("/api/conversations").json()["id"]
        self.send(
            self.alice, thread_id, "不要 S001",
            tool_calls(("exclude_listings", {"exclude": ["S001"]})),
            AIMessage(content="好的。"),
        )
        self.assertEqual(self.alice.get("/api/me/listings").json(), {"shortlist": [], "excluded": ["S001"]})
        # Shortlisting an excluded listing takes it off the exclusions, as in chat.
        self.assertEqual(self.alice.post("/api/me/shortlist", json={"listing_id": "S001"}).json(), {"shortlist": ["S001"], "excluded": []})
        self.send(self.alice, thread_id, "也不要 S002", tool_calls(("exclude_listings", {"exclude": ["S002"]})), AIMessage(content="好的。"))
        self.assertEqual(self.alice.delete("/api/me/excluded/S002").json(), {"shortlist": ["S001"], "excluded": []})

    def test_the_long_term_profile_is_edited_switched_and_deleted_on_the_page(self):
        self.sign_up(self.alice, "alice")
        empty = self.alice.get("/api/me/profile").json()
        self.assertEqual((empty["memory"], empty["items"], empty["opening"]), ("undecided", [], None))

        # Saving on the page switches memory on, with the page as each criterion's source.
        edited = self.alice.put("/api/me/profile", json={"changes": {"max_price_sgd": 1500, "district_code": "D05"}}).json()
        self.assertEqual(edited["memory"], "on")
        self.assertEqual(edited["preferences"], {"max_price_sgd": 1500, "district_code": "D05"})
        self.assertEqual(edited["sources"]["district_code"]["via"], "profile")
        self.assertEqual(edited["opening"]["zh"], "已按你的长期资料设好条件：每月最高预算 S$1,500；地区 D05。说“开始找”就按这些条件搜索，也可以直接告诉我新的需求。")
        self.assertEqual(self.alice.put("/api/me/profile", json={"changes": {"faculty": "Faculty of Law"}}).status_code, 400)
        self.assertEqual(self.alice.put("/api/me/profile", json={"changes": {"max_price_sgd": -5}}).status_code, 400)
        dropped = self.alice.put("/api/me/profile", json={"changes": {"district_code": None}}).json()
        self.assertEqual((dropped["preferences"], list(dropped["sources"])), ({"max_price_sgd": 1500}, ["max_price_sgd"]))

        # Off pauses it: kept and shown, but neither changed nor used by a new conversation.
        paused = self.alice.put("/api/me/memory", json={"on": False}).json()
        self.assertEqual((paused["memory"], paused["preferences"], paused["opening"]), ("off", {"max_price_sgd": 1500}, None))
        self.assertEqual(self.alice.put("/api/me/profile", json={"changes": {"max_price_sgd": 2000}}).status_code, 409)
        plain = self.alice.post("/api/conversations").json()["id"]
        self.assertEqual(self.alice.get(f"/api/conversations/{plain}/messages").json(), [])

        # On again: a new conversation starts from the profile, with a first message saying so.
        self.alice.put("/api/me/memory", json={"on": True})
        started = self.alice.post("/api/conversations", json={"language": "en"}).json()["id"]
        history = self.alice.get(f"/api/conversations/{started}/messages").json()
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0]["text"].startswith("Your long-term profile's criteria are set: maximum monthly budget S$1,500."))
        self.assertTrue(history[0]["steps"][0].startswith("Long-term profile: started from the criteria saved on"))
        self.assertEqual(self.alice.get(f"/api/conversations/{started}").json()["preferences"], {"max_price_sgd": 1500})

        deleted = self.alice.delete("/api/me/profile").json()
        self.assertEqual((deleted["memory"], deleted["preferences"]), ("on", {}))
        self.assertEqual(self.bob.get("/api/me/profile").status_code, 401)

    def test_a_failed_turn_leaves_a_reply_saying_so(self):
        self.sign_up(self.alice, "alice")
        thread_id = self.alice.post("/api/conversations").json()["id"]

        def broken(messages):
            raise RuntimeError("the model is unavailable")

        with self.assertLogs(level="ERROR"):
            name, data = self.send(self.alice, thread_id, "预算1300", broken)[-1]
        self.assertEqual((name, data["message"]), ("error", "Something went wrong with this message. Try again in a moment."))
        # Read again later, the conversation shows the turn is over instead of waiting for a reply.
        history = self.alice.get(f"/api/conversations/{thread_id}/messages").json()
        self.assertEqual(
            history,
            [
                {"role": "user", "text": "预算1300"},
                {"role": "assistant", "text": "处理这条消息时出错了，没有回复。请重新发送这条消息。", "steps": ["这一轮出错了（RuntimeError），没有回复"]},
            ],
        )
        # The message sent again is answered as usual.
        name, data = self.send(self.alice, thread_id, "预算1300", AIMessage(content="好的，还有别的条件吗？"))[-1]
        self.assertEqual((name, data["text"]), ("reply", "好的，还有别的条件吗？"))
        self.assertEqual(len(self.alice.get(f"/api/conversations/{thread_id}/messages").json()), 4)

    def test_the_sign_up_criteria_become_the_long_term_profile(self):
        self.sign_up(self.alice, "alice")
        criteria = {"max_price_sgd": 3000, "rental_scope": "entire_unit", "min_bedrooms": 2}
        saved = self.alice.put("/api/me/profile", json={"changes": criteria, "via": "signup"}).json()
        self.assertEqual((saved["memory"], saved["preferences"]), ("on", criteria))
        self.assertEqual({source["via"] for source in saved["sources"].values()}, {"signup"})
        # The first conversation starts from them.
        started = self.alice.post("/api/conversations").json()["id"]
        self.assertEqual(self.alice.get(f"/api/conversations/{started}").json()["preferences"], criteria)

    def test_a_conversation_saves_only_what_it_changed(self):
        self.sign_up(self.alice, "alice")
        self.alice.put("/api/me/profile", json={"changes": {"max_price_sgd": 1300, "rental_scope": "room"}})
        thread_id = self.alice.post("/api/conversations").json()["id"]
        name, reply = self.send(
            self.alice, thread_id, "只看D05",
            tool_calls(("search_listings", {"set": {"district_code": "D05"}, "user_quote": "只看D05"})),
            AIMessage(content=""),
        )[-1]
        # The reply says what is not saved to the long-term profile yet, for the page to show.
        self.assertEqual([row["field"] for row in reply["profile_changes"]], ["district_code"])
        # Meanwhile the page raises the budget; the conversation did not change it, so it stays.
        self.alice.put("/api/me/profile", json={"changes": {"max_price_sgd": 3000}})
        preview = self.alice.get(f"/api/conversations/{thread_id}/profile").json()
        self.assertEqual(preview["memory"], "on")
        self.assertEqual([(row["field"], row["before"]["zh"], row["after"]["zh"]) for row in preview["changes"]], [("district_code", "不限", "D05")])

        saved = self.alice.post(f"/api/conversations/{thread_id}/profile", json={}).json()
        self.assertEqual(saved["changes"], preview["changes"])
        self.assertEqual(saved["profile"]["preferences"], {"max_price_sgd": 3000, "rental_scope": "room", "district_code": "D05"})
        self.assertEqual(saved["profile"]["sources"]["district_code"]["quote"], "只看D05")
        self.assertEqual(self.alice.get(f"/api/conversations/{thread_id}/profile").json()["changes"], [])
        self.assertEqual(self.alice.get(f"/api/conversations/{thread_id}").json()["profile_changes"], [])

        # While memory is off, saving needs the user's agreement to switch it on.
        self.alice.put("/api/me/memory", json={"on": False})
        self.send(
            self.alice, thread_id, "预算1400",
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1400}, "user_quote": "预算1400"})),
            AIMessage(content=""),
        )
        self.assertEqual(self.alice.post(f"/api/conversations/{thread_id}/profile", json={}).status_code, 409)
        switched = self.alice.post(f"/api/conversations/{thread_id}/profile", json={"switch_on": True}).json()
        self.assertEqual((switched["profile"]["memory"], switched["profile"]["preferences"]["max_price_sgd"]), ("on", 1400))
        self.assertEqual(self.bob.post(f"/api/conversations/{thread_id}/profile", json={}).status_code, 401)

    def test_auto_save_is_offered_until_chosen_and_saves_criteria_as_they_change(self):
        self.sign_up(self.alice, "alice")
        fresh = self.alice.get("/api/me/profile").json()
        self.assertEqual((fresh["memory"], fresh["auto_save"], fresh["auto_save_offer"]), ("undecided", False, True))
        thread_id = self.alice.post("/api/conversations").json()["id"]
        self.send(
            self.alice, thread_id, "预算1300",
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "预算1300"})),
            AIMessage(content=""),
        )

        # Switched on from the conversation: memory too, and what it changed so far is saved at once.
        switched = self.alice.post(f"/api/conversations/{thread_id}/auto-save").json()
        self.assertEqual([row["field"] for row in switched["changes"]], ["max_price_sgd"])
        profile = switched["profile"]
        self.assertEqual((profile["memory"], profile["auto_save"], profile["auto_save_offer"]), ("on", True, False))
        self.assertEqual(profile["preferences"], {"max_price_sgd": 1300})
        self.assertEqual(self.alice.get(f"/api/conversations/{thread_id}").json()["profile_changes"], [])

        name, reply = self.send(
            self.alice, thread_id, "只看D05",
            tool_calls(("search_listings", {"set": {"district_code": "D05"}, "user_quote": "只看D05"})),
            AIMessage(content=""),
        )[-1]
        self.assertIn("已更新本次对话的条件，并自动存到长期资料：地区 不限 → D05", reply["text"])
        self.assertEqual(reply["profile_changes"], [])
        self.assertEqual(self.alice.get("/api/me/profile").json()["preferences"], {"max_price_sgd": 1300, "district_code": "D05"})

        # Switched off on the page: offered again until the offer is closed.
        off = self.alice.put("/api/me/auto-save", json={"on": False}).json()
        self.assertEqual((off["auto_save"], off["auto_save_offer"]), (False, True))
        self.alice.put("/api/me/memory", json={"on": False})
        self.assertEqual(self.alice.post(f"/api/conversations/{thread_id}/auto-save").status_code, 409)

        # Closing the offer is for good.
        self.sign_up(self.bob, "bob")
        self.assertTrue(self.bob.get("/api/me/profile").json()["auto_save_offer"])
        closed = self.bob.delete("/api/me/auto-save/offer").json()
        self.assertEqual((closed["memory"], closed["auto_save"], closed["auto_save_offer"]), ("undecided", False, False))
        self.assertEqual(self.bob.post(f"/api/conversations/{thread_id}/auto-save").status_code, 404)

    def test_a_registration_code_is_needed_to_sign_up_when_the_server_has_one(self):
        from fastapi.testclient import TestClient

        from server import create_app

        self.assertFalse(self.alice.get("/api/options").json()["invite_code_required"])
        app = create_app(self.listings, self.model, self.storage, self.checkpointer, listing_checker=active_links, registration_code="nus-5105")
        alice, bob = TestClient(app), TestClient(app)
        self.assertTrue(alice.get("/api/options").json()["invite_code_required"])

        for code in (None, "", "nus-5106"):
            refused = alice.post("/api/register", json={"username": "alice", "password": PASSWORD, "invite_code": code})
            self.assertEqual((refused.status_code, refused.json()["detail"]), (400, "That invite code is not right. Check it with whoever invited you."))
        # Nothing was created.
        self.assertEqual(alice.post("/api/login", json={"username": "alice", "password": PASSWORD}).status_code, 400)

        signed_up = alice.post("/api/register", json={"username": "alice", "password": PASSWORD, "invite_code": " nus-5105 "})
        self.assertEqual(signed_up.status_code, 200, signed_up.text)
        # Signing in never needs it.
        self.assertEqual(bob.post("/api/login", json={"username": "alice", "password": PASSWORD}).status_code, 200)

    def test_shortlists_kept_per_conversation_become_the_accounts_once(self):
        from agent import build_agent
        from server import create_app

        storage = empty_storage()
        profiles = UserProfiles(storage)
        # Before: a long-term profile and two conversations, each with its own lists.
        profiles.save("alice", {"preferences": {"max_price_sgd": 1300}, "shortlisted_listing_ids": ["S004"], "excluded_listing_ids": ["S003"]})
        older, newer = storage.new_thread("alice"), storage.new_thread("alice")
        writer = build_agent(self.listings, self.model, self.checkpointer)
        for thread_id, shortlist, excluded in ((older, ["S001", "S002"], []), (newer, ["S003"], ["S001"])):
            writer.update_state({"configurable": {"thread_id": thread_id}}, {"shortlisted_listing_ids": shortlist, "excluded_listing_ids": excluded}, as_node="finalize")
            storage.touch(thread_id, "hi")

        create_app(self.listings, self.model, storage, self.checkpointer, listing_checker=active_links)
        # The latest conversation decides a listing in several lists.
        self.assertEqual(profiles.listings("alice"), (["S004", "S002", "S003"], ["S001"]))
        profiles.unmark("alice", ["S004"], "shortlist")
        create_app(self.listings, self.model, storage, self.checkpointer, listing_checker=active_links)
        self.assertEqual(profiles.listings("alice"), (["S002", "S003"], ["S001"]))

    def test_the_reply_follows_the_message_then_the_interface_language(self):
        self.sign_up(self.alice, "alice")
        thread_id = self.alice.post("/api/conversations").json()["id"]

        # A message with no language of its own, such as a number, is answered in the interface language.
        name, reply = self.send(
            self.alice, thread_id, "1300",
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "1300"})),
            AIMessage(content=""),
            language="en",
        )[-1]
        self.assertIn("Updated this conversation's criteria: maximum monthly budget any → S$1,300", reply["text"])
        self.assertEqual(reply["preferences"], {"max_price_sgd": 1300})

        # A Chinese message is answered in Chinese, whatever the interface language.
        name, reply = self.send(
            self.alice, thread_id, "预算改成1500",
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500}, "user_quote": "预算改成1500"})),
            AIMessage(content=""),
            language="en",
        )[-1]
        self.assertIn("已更新本次对话的条件", reply["text"])

    def test_other_users_cannot_reach_a_conversation(self):
        self.sign_up(self.alice, "alice")
        self.sign_up(self.bob, "bob")
        thread_id = self.alice.post("/api/conversations").json()["id"]

        self.assertEqual(self.bob.get("/api/conversations").json(), [])
        self.assertEqual(self.bob.get(f"/api/conversations/{thread_id}/messages").status_code, 404)
        sent = self.bob.post(f"/api/conversations/{thread_id}/messages", json={"message": "你好"})
        self.assertEqual((sent.status_code, sent.json()["detail"]), (404, "Conversation not found."))
        self.assertEqual(self.bob.delete(f"/api/conversations/{thread_id}").status_code, 404)
        self.assertEqual(self.client().get(f"/api/conversations/{thread_id}/messages").status_code, 401)
        self.assertEqual(self.alice.get(f"/api/conversations/{thread_id}/messages").json(), [])

    def test_deleting_a_conversation_and_then_all_my_data(self):
        self.sign_up(self.alice, "alice")
        other_device = self.client()
        other_device.post("/api/login", json={"username": "alice", "password": PASSWORD})
        first = self.alice.post("/api/conversations").json()["id"]
        second = self.alice.post("/api/conversations").json()["id"]
        self.send(self.alice, first, "你好", AIMessage(content="你好！"))
        self.send(self.alice, second, "你好", AIMessage(content="你好！"))
        profiles = UserProfiles(self.storage)
        profiles.set_consent("alice", True)
        profiles.save("alice", {"preferences": {"max_price_sgd": 1300}})
        profiles.set_faculty("alice", "School of Computing")

        self.assertEqual(self.alice.delete(f"/api/conversations/{first}").status_code, 200)
        self.assertEqual([thread["id"] for thread in self.alice.get("/api/conversations").json()], [second])
        self.assertEqual(self.alice.get(f"/api/conversations/{first}/messages").status_code, 404)
        self.assertIsNone(self.checkpointer.get_tuple({"configurable": {"thread_id": first}}))

        self.assertEqual(self.alice.delete("/api/me/data").status_code, 200)
        # Every session ends; the account stays.
        self.assertEqual(self.alice.get("/api/me").status_code, 401)
        self.assertEqual(other_device.get("/api/me").status_code, 401)
        self.assertIsNone(self.checkpointer.get_tuple({"configurable": {"thread_id": second}}))
        self.assertIsNone(profiles.consent("alice"))
        self.assertIsNone(profiles.faculty("alice"))
        self.assertEqual(self.alice.post("/api/login", json={"username": "alice", "password": PASSWORD}).status_code, 200)
        self.assertEqual(self.alice.get("/api/conversations").json(), [])


    def test_the_faculty_is_chosen_at_sign_up_and_changed_in_settings(self):
        listed = self.client().get("/api/faculties").json()
        self.assertEqual(len(listed), 16)
        self.assertIn(
            {"name": "NUS Business School", "zh": "商学院", "campus": "Kent Ridge", "code": "BUS", "latitude": 1.292522, "longitude": 103.774133},
            listed,
        )
        signed_up = self.alice.post("/api/register", json={"username": "alice", "password": PASSWORD, "faculty": "商学院"})
        self.assertEqual(signed_up.json(), {"username": "alice", "faculty": "NUS Business School"})

        changed = self.alice.put("/api/me/faculty", json={"faculty": "Faculty of Law"})
        self.assertEqual(changed.json()["faculty"], "Faculty of Law")
        wrong = self.alice.put("/api/me/faculty", json={"faculty": "Yale-NUS College"})
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (400, "Choose a faculty from the list."))
        self.assertIsNone(self.alice.put("/api/me/faculty", json={"faculty": None}).json()["faculty"])
        # A sign-up with an unknown faculty creates no account.
        refused = self.bob.post("/api/register", json={"username": "bob", "password": PASSWORD, "faculty": "Yale-NUS College"})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self.bob.post("/api/login", json={"username": "bob", "password": PASSWORD}).status_code, 400)

    def test_a_lost_database_connection_asks_to_try_again(self):
        self.sign_up(self.alice, "alice")
        thread_id = self.alice.post("/api/conversations").json()["id"]
        lost = OperationalError("server closed the connection unexpectedly")

        with patch("server.load_listings", side_effect=lost):
            page = self.alice.get("/api/listings")
        with patch.object(self.storage, "touch", side_effect=lost):
            found = self.send(self.alice, thread_id, "预算1300")

        self.assertEqual((page.status_code, page.json()), (503, {"detail": UNAVAILABLE}))
        self.assertEqual(found, [("error", {"message": UNAVAILABLE})])
        # Nothing is left broken: the next request works.
        self.assertEqual(self.alice.get("/api/listings").status_code, 200)


if __name__ == "__main__":
    unittest.main()
