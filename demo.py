import sys
from contextlib import closing

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent import build_agent
from config import env
from graph import build_graph
from mock_db import create_database


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    flags = {arg for arg in args if arg.startswith("--")}
    chat_mode = "--chat" in flags
    message = " ".join(arg for arg in args if not arg.startswith("--")).strip()
    api_key = env("OPENAI_API_KEY")
    model_name = env("OPENAI_MODEL")

    if flags - {"--chat", "--workflow", "--trace"} or not (chat_mode or message):
        raise SystemExit(
            'Usage: python demo.py [--workflow] [--trace] "your rental requirements"\n'
            "       python demo.py [--workflow] [--trace] --chat\n"
            "--workflow runs the fixed LangGraph workflow baseline; --trace prints agent tool calls, link checks and rejected replies."
        )
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY before running the demo")
    if not model_name:
        raise SystemExit("Set OPENAI_MODEL to a model available to your account")

    with closing(create_database()) as connection:
        # Reasoning models such as gpt-5.x only accept function tools on the Responses API.
        model = ChatOpenAI(
            model=model_name,
            api_key=api_key,
            use_responses_api="--workflow" not in flags,
        )
        memory = MemorySaver(
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[("models", "SearchPreferences")]
            )
        )
        graph = (build_graph if "--workflow" in flags else build_agent)(connection, model, memory)
        config = {"configurable": {"thread_id": "demo"}}

        def reply(text: str) -> str:
            result = graph.invoke({"message": text}, config=config)
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
                    print(f"Agent：{reply(message)}")
            return

        print(reply(message))


if __name__ == "__main__":
    main()
