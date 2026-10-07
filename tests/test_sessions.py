import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent import build_agent
from mock_db import create_mock_database
from sessions import memory_storage, open_sqlite
from tests.test_agent import ScriptedModel, active_links, tool_calls


class SessionTest(unittest.TestCase):
    def test_a_conversation_continues_after_a_restart(self):
        request = "预算1300，收藏 S001"
        first = ScriptedModel(
            tool_calls(
                ("search_listings", {"set": {"max_price_sgd": 1300}, "user_quote": "预算1300"}),
                ("shortlist", {"add": ["S001"]}),
            ),
            AIMessage(content="好的。"),
        )
        later = ScriptedModel(AIMessage(content="好的，我们接着看。"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sessions.sqlite"
            storage, memory = open_sqlite(path)
            with closing(storage), closing(memory.conn), closing(create_mock_database()) as listings:
                thread_id = storage.new_thread("alice")
                storage.touch(thread_id, request)
                config = {"configurable": {"thread_id": thread_id}}
                build_agent(listings, first, memory, listing_checker=active_links).invoke({"message": request}, config=config)

            # Next day, new process: new connections to the same file.
            storage, memory = open_sqlite(path)
            with closing(storage), closing(memory.conn), closing(create_mock_database()) as listings:
                again = storage.latest_thread("alice")
                result = build_agent(listings, later, memory, listing_checker=active_links).invoke(
                    {"message": "我回来了"}, config={"configurable": {"thread_id": again}}
                )

        self.assertEqual(again, thread_id)
        self.assertEqual(result["preferences"].max_price_sgd, 1300)
        self.assertEqual(result["shortlisted_listing_ids"], ["S001"])
        self.assertEqual(result["messages"][0].content, request)

    def test_each_user_sees_only_their_own_conversations(self):
        storage = memory_storage()
        self.addCleanup(storage.close)
        clock = (f"2026-10-06T10:00:0{tick}.000" for tick in range(9))
        with patch("sessions._now", side_effect=clock):
            first = storage.new_thread("alice")
            second = storage.new_thread("alice")
            other = storage.new_thread("bob")
            # The latest activity comes first; the first message becomes the title.
            storage.touch(first, "  预算 1300，\n想离 NUS 近一点，最好是合租单间  ")
            storage.touch(first, "第二条消息不改标题")

        listed = storage.threads("alice")
        self.assertEqual([thread["id"] for thread in listed], [first, second])
        self.assertEqual(listed[0]["title"], "预算 1300， 想离 NUS 近一点，")
        self.assertEqual(listed[1]["title"], "")
        self.assertNotIn("/", first)
        self.assertTrue(storage.owns("alice", first))
        self.assertFalse(storage.owns("bob", first))
        self.assertEqual(storage.latest_thread("bob"), other)

        storage.forget_thread(first)
        self.assertEqual(storage.latest_thread("alice"), second)
        self.assertFalse(storage.owns("alice", first))
        self.assertIsNone(storage.latest_thread("carol"))


if __name__ == "__main__":
    unittest.main()
