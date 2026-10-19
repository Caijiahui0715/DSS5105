import sys
from contextlib import closing

from langchain_openai import ChatOpenAI
from psycopg import OperationalError

from agent import build_agent, opening_state
from config import env
from graph import build_graph
from group_db import UNAVAILABLE, open_database
from profiles import UserProfiles
from sessions import open_storage


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    # --user=NAME says whose saved conversation to continue; other -- arguments are flags.
    # Names are the web demo's user names, so the same person sees the same conversations.
    user = next((arg.split("=", 1)[1] for arg in args if arg.startswith("--user=")), "demo").strip().lower()
    flags = {arg for arg in args if arg.startswith("--") and not arg.startswith("--user=")}
    chat_mode = "--chat" in flags
    message = " ".join(arg for arg in args if not arg.startswith("--")).strip()
    api_key = env("OPENAI_API_KEY")
    model_name = env("OPENAI_MODEL")

    if flags - {"--chat", "--workflow", "--trace", "--new"} or not (chat_mode or message) or not user:
        raise SystemExit(
            'Usage: python demo.py [--workflow] [--trace] [--user=NAME] [--new] "your rental requirements"\n'
            "       python demo.py [--workflow] [--trace] [--user=NAME] [--new] --chat\n"
            "--workflow runs the fixed LangGraph workflow baseline; --trace prints agent tool calls, link checks and rejected replies.\n"
            "--user=NAME continues that user's latest conversation (default: demo, no password); --new starts a new one."
        )
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY before running the demo")
    if not model_name:
        raise SystemExit("Set OPENAI_MODEL to a model available to your account")

    # An unreachable database stops here with what to fix.
    database = open_database()
    with closing(database) as connection:
        storage, memory = open_storage(database)
        # Reasoning models such as gpt-5.x only accept function tools on the Responses API.
        model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            use_responses_api="--workflow" not in flags,
        )
        workflow = "--workflow" in flags
        # Long-term memory is an agent feature; the workflow baseline stays as it was.
        profiles = UserProfiles(storage)
        graph = (
            build_graph(connection, model, memory)
            if workflow
            else build_agent(connection, model, memory, profiles=profiles)
        )
        # The workflow keeps separate threads: its state has a different shape from the agent's.
        session_user = f"{user}@workflow" if workflow else user
        thread_id = None if "--new" in flags else storage.latest_thread(session_user)
        if thread_id:
            print(f"继续 {user} 上次的对话（{thread_id}）；加 --new 可以开始新对话。")
        config = {"configurable": {"thread_id": thread_id or storage.new_thread(session_user)}}
        # A new conversation starts from the long-term profile while memory is on, as on the web page.
        if not thread_id and not workflow and (opening := opening_state(profiles, user, "zh")):
            graph.update_state(config, opening, as_node="finalize")
            print(f"Agent：{opening['messages'][0].content}")
        thread_id = config["configurable"]["thread_id"]
        user_input = {} if workflow else {"user_id": user}

        def reply(text: str) -> str:
            storage.touch(thread_id, text)
            result = graph.invoke({"message": text, **user_input}, config=config)
            if "--trace" in flags:
                for line in result.get("trace", []):
                    print(f"  {line}")
            return result["response"]

        if chat_mode:
            print("输入租房需求；输入 exit 退出。")
            while True:
                try:
                    message = input("\n你：").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if message.casefold() in {"exit", "quit"}:
                    break
                if message:
                    try:
                        print(f"Agent：{reply(message)}")
                    except OperationalError:
                        # The next message connects again.
                        print(f"Agent：{UNAVAILABLE}")
            return

        print(reply(message))


if __name__ == "__main__":
    main()
