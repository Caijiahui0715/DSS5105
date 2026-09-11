import sys
from contextlib import closing

from langchain_openai import ChatOpenAI

from config import env
from graph import build_graph
from mock_db import create_mock_database


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    message = " ".join(sys.argv[1:]).strip()
    api_key = env("OPENAI_API_KEY")
    model_name = env("OPENAI_MODEL")

    if not message:
        raise SystemExit('Usage: python demo.py "your rental requirements"')
    if not api_key:
        raise SystemExit("Set OPENAI_API_KEY before running the demo")
    if not model_name:
        raise SystemExit("Set OPENAI_MODEL to a model available to your account")

    with closing(create_mock_database()) as connection:
        model = ChatOpenAI(model=model_name, api_key=api_key)
        result = build_graph(connection, model).invoke({"message": message})

    print(result["response"])


if __name__ == "__main__":
    main()
