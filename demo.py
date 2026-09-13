import sys
from contextlib import closing

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from config import env
from graph import build_graph
from mock_db import create_mock_database


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    chat_mode = args == ["--chat"]
    message = "" if chat_mode else " ".join(args).strip()
    api_key = env("OPENAI_API_KEY")
    model_name = env("OPENAI_MODEL")

    if not chat_mode and not message:
        raise SystemExit('Usage: python demo.py "your rental requirements" or python demo.py --chat')
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY before running the demo")
    if not model_name:
        raise SystemExit("Set OPENAI_MODEL to a model available to your account")

    with closing(create_mock_database()) as connection:
        model = ChatOpenAI(model=model_name, api_key=api_key)
        memory = MemorySaver(
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[("models", "SearchPreferences")]
            )
        )
        graph = build_graph(connection, model, memory)
        config = {"configurable": {"thread_id": "demo"}}
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
                    result = graph.invoke({"message": message}, config=config)
                    print(f"Agent：{result['response']}")
            return

        result = graph.invoke({"message": message}, config=config)

    print(result["response"])


if __name__ == "__main__":
    main()
