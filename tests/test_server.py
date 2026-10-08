import importlib.util
import json
import unittest

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from mock_db import create_mock_database
from profiles import UserProfiles
from sessions import memory_storage, serializer
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
        self.storage = memory_storage()
        self.checkpointer = MemorySaver(serde=serializer())
        self.app = create_app(self.listings, self.model, self.storage, self.checkpointer, listing_checker=active_links)
        self.client = lambda: TestClient(self.app)
        self.alice, self.bob = self.client(), self.client()

    def tearDown(self):
        self.listings.close()
        self.storage.close()

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
        self.assertEqual((taken.status_code, taken.json()["detail"]), (400, "这个用户名已被注册。"))
        wrong = self.bob.post("/api/login", json={"username": "alice", "password": "not-the-password"})
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (400, "用户名或密码不正确。"))
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
        # The user is known to the agent: it offers to remember the criteria.
        self.assertIn("要我记住这些条件吗？", reply["text"])
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

    def test_a_reopened_conversation_has_its_criteria_listings_and_shortlist(self):
        self.sign_up(self.alice, "alice")
        thread_id = self.alice.post("/api/conversations").json()["id"]
        self.assertEqual(
            self.alice.get(f"/api/conversations/{thread_id}").json(),
            {"id": thread_id, "preferences": {}, "recommendations": None, "shortlist": []},
        )
        # A favorite before the first message is kept too.
        self.assertEqual(self.alice.post(f"/api/conversations/{thread_id}/shortlist", json={"listing_id": "S002"}).json(), {"shortlist": ["S002"]})
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
        self.assertEqual(snapshot["recommendations"]["listings"], shown)
        first = shown[0]["listing_id"]
        self.assertEqual(self.alice.post(f"/api/conversations/{thread_id}/shortlist", json={"listing_id": first}).json()["shortlist"], ["S002", first])
        self.assertEqual(self.alice.delete(f"/api/conversations/{thread_id}/shortlist/S002").json()["shortlist"], [first])
        self.assertEqual(self.alice.post(f"/api/conversations/{thread_id}/shortlist", json={"listing_id": "NOPE"}).status_code, 404)
        self.assertEqual(self.bob.get(f"/api/conversations/{thread_id}").status_code, 401)

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
        self.assertIn("Should I remember these criteria?", reply["text"])
        self.assertEqual(reply["preferences"], {"max_price_sgd": 1300})

        # A Chinese message is answered in Chinese, whatever the interface language.
        name, reply = self.send(
            self.alice, thread_id, "预算改成1500",
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1500}, "user_quote": "预算改成1500"})),
            AIMessage(content=""),
            language="en",
        )[-1]
        self.assertIn("已保存条件变更", reply["text"])

    def test_other_users_cannot_reach_a_conversation(self):
        self.sign_up(self.alice, "alice")
        self.sign_up(self.bob, "bob")
        thread_id = self.alice.post("/api/conversations").json()["id"]

        self.assertEqual(self.bob.get("/api/conversations").json(), [])
        self.assertEqual(self.bob.get(f"/api/conversations/{thread_id}/messages").status_code, 404)
        sent = self.bob.post(f"/api/conversations/{thread_id}/messages", json={"message": "你好"})
        self.assertEqual((sent.status_code, sent.json()["detail"]), (404, "找不到这段对话。"))
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
        self.assertEqual((wrong.status_code, wrong.json()["detail"]), (400, "请从列表里选择学院。"))
        self.assertIsNone(self.alice.put("/api/me/faculty", json={"faculty": None}).json()["faculty"])
        # A sign-up with an unknown faculty creates no account.
        refused = self.bob.post("/api/register", json={"username": "bob", "password": PASSWORD, "faculty": "Yale-NUS College"})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self.bob.post("/api/login", json={"username": "bob", "password": PASSWORD}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
