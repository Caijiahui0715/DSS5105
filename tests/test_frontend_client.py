"""The Streamlit frontend's backend client (app/adapters) against server.py: the two sides agree."""
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from mock_db import create_mock_database, empty_storage
from sessions import serializer
from tests.test_agent import ScriptedModel, active_links, tool_calls

APP = Path(__file__).resolve().parents[1] / "app"
BASE = "http://backend.test"


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "run `uv add fastapi uvicorn` to test the web demo")
class FrontendClientTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from server import create_app

        # The frontend's modules use its own folder as the import root.
        sys.path.insert(0, str(APP))
        self.addCleanup(sys.path.remove, str(APP))
        from adapters.backend_client import BackendClient

        self.listings, self.storage = create_mock_database(), empty_storage()
        self.model = ScriptedModel()
        app = create_app(self.listings, self.model, self.storage, MemorySaver(serde=serializer()), listing_checker=active_links)
        self.http = TestClient(app)
        self.client = BackendClient(BASE, opener=self.open)

    def tearDown(self):
        self.listings.close()

    def open(self, request, timeout=None):
        """urlopen, answered by the app; only the Authorization header signs in, never a cookie."""
        self.http.cookies.clear()
        body = json.loads(request.data) if request.data else None
        reply = self.http.request(request.get_method(), request.full_url.removeprefix(BASE), json=body, headers=dict(request.header_items()))
        content = io.BytesIO(reply.text.encode("utf-8"))
        if reply.status_code >= 400:
            raise HTTPError(request.full_url, reply.status_code, "error", {}, content)
        return content

    def test_a_signed_in_frontend_chats_saves_and_reopens(self):
        from adapters.backend_client import BackendClient, SessionExpired
        from adapters.http_agent_api import HttpAgentApi, recommendations
        from domain.criteria import from_backend

        faculty = self.client.faculties()[0]
        options = self.client.options()
        account = self.client.register("alice", "password123", faculty["name"])
        self.assertEqual((account["username"], account["faculty"]), ("alice", faculty["name"]))
        self.assertEqual(self.client.me()["username"], "alice")
        self.assertIn("D05", [district["code"] for district in options["districts"]])
        self.assertEqual(len(self.client.listings()), 12)
        self.assertEqual(self.client.listing("S001")["listing"]["listing_id"], "S001")
        self.assertIsNone(self.client.listing("NOPE"))

        conversation = {"thread_id": None}
        progress = []
        self.model.steps.extend([
            tool_calls(("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "My budget is SGD 1300"})),
            AIMessage(content=""),
        ])
        response = HttpAgentApi(self.client).respond(conversation, "My budget is SGD 1300", "en", progress.append)

        self.assertTrue(conversation["thread_id"])
        self.assertIn("Understanding your request", progress)
        self.assertIn("Updated this conversation's criteria: maximum monthly budget any → S$1,300", response.text)
        self.assertEqual(response.requirements.max_budget, 1300)
        self.assertEqual(response.criteria["preferences"], {"max_price_sgd": 1300})
        self.assertEqual(response.criteria["items"][0]["field"], "max_price_sgd")
        self.assertTrue(response.recommendations)
        first = response.recommendations[0]
        self.assertEqual((first.rank, first.score, first.is_demo_score), (1, None, False))
        self.assertIn(first.evaluation.status, {"pass", "needs_confirmation"})
        self.assertEqual(first.facts["listing_id"], first.listing_id)

        self.assertIsNone(response.comparison)
        thread_id = conversation["thread_id"]
        # A comparison reaches the page as its table, and stays with the conversation.
        pair = [rec.listing_id for rec in response.recommendations[:2]]
        self.model.steps.extend([tool_calls(("compare_listings", {"listing_ids": pair})), AIMessage(content="")])
        compared = HttpAgentApi(self.client).respond(conversation, f"Compare {pair[0]} and {pair[1]}.", "en")
        self.assertEqual(compared.comparison["listing_ids"], pair)
        self.assertEqual(compared.comparison["rows"][0]["label"]["en"], "Monthly rent")
        self.assertEqual(self.client.conversation(thread_id)["comparison"], compared.comparison)
        self.assertEqual(self.client.shortlist_add(first.listing_id), {"shortlist": [first.listing_id], "excluded": []})
        snapshot = self.client.conversation(thread_id)
        self.assertEqual(from_backend(snapshot["preferences"])[0].max_budget, 1300)
        self.assertEqual([rec.listing_id for rec in recommendations(snapshot["recommendations"])], [rec.listing_id for rec in response.recommendations])
        self.assertEqual(snapshot["shortlist"], [first.listing_id])
        self.assertEqual([message["role"] for message in self.client.messages(thread_id)], ["user", "assistant", "user", "assistant"])
        self.assertEqual([thread["id"] for thread in self.client.conversations()], [thread_id])
        self.assertEqual(self.client.shortlist_remove(first.listing_id)["shortlist"], [])
        self.assertEqual(self.client.my_listings(), {"shortlist": [], "excluded": []})
        self.assertIsNone(self.client.set_faculty(None)["faculty"])

        # The long-term profile: save this conversation's criteria after seeing what changes.
        self.assertEqual([row["field"] for row in self.client.profile_changes(thread_id)["changes"]], ["max_price_sgd"])
        saved = self.client.save_profile(thread_id)
        self.assertEqual((saved["profile"]["memory"], saved["profile"]["preferences"]), ("on", {"max_price_sgd": 1300}))
        edited = self.client.edit_profile({"max_price_sgd": 1500, "district_code": "D05"})
        self.assertEqual(edited["preferences"], {"max_price_sgd": 1500, "district_code": "D05"})
        self.assertEqual(self.client.set_memory(False)["memory"], "off")
        self.assertIsNone(self.client.profile()["opening"])
        self.client.set_memory(True)
        started = self.client.new_conversation("en")
        self.assertEqual(self.client.conversation(started)["preferences"], {"max_price_sgd": 1500, "district_code": "D05"})
        self.assertEqual(self.client.delete_profile()["preferences"], {})

        # One conversation is deleted; the others stay.
        extra = self.client.new_conversation("en")
        self.assertEqual(self.client.delete_conversation(extra), {"ok": True})
        self.assertNotIn(extra, [thread["id"] for thread in self.client.conversations()])
        self.assertIn(thread_id, [thread["id"] for thread in self.client.conversations()])

        self.client.delete_my_data()
        with self.assertRaises(SessionExpired):
            BackendClient(BASE, account["token"], opener=self.open).me()

    def test_backend_messages_and_an_unreachable_backend(self):
        from adapters.backend_client import BackendClient, BackendError

        with self.assertRaises(BackendError) as wrong:
            self.client.sign_in("nobody", "password123")
        self.assertEqual((wrong.exception.status, wrong.exception.detail), (400, "用户名或密码不正确。"))

        def down(request, timeout=None):
            raise URLError(ConnectionRefusedError(111, "Connection refused"))

        with self.assertRaises(BackendError) as unreachable:
            BackendClient(BASE, opener=down).faculties()
        self.assertIsNone(unreachable.exception.status)

        def cut_off(request, timeout=None):
            # A reply stream that times out after the first progress line.
            def lines():
                yield b"event: progress\n"
                yield b'data: {"zh": "\\u6b63\\u5728\\u641c\\u7d22", "en": "Searching"}\n'
                raise TimeoutError("timed out")

            stream = lines()
            return type("Response", (), {"__iter__": lambda self: stream, "__enter__": lambda self: self, "__exit__": lambda self, *exc: False})()

        events = BackendClient(BASE, "token", opener=cut_off).send("thread", "hi", "en")
        self.assertEqual(next(events), ("progress", {"zh": "正在搜索", "en": "Searching"}))
        with self.assertRaises(BackendError) as broken:
            next(events)
        self.assertEqual(broken.exception.status, 504)


if __name__ == "__main__":
    unittest.main()
