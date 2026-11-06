"""Run the boundary probes on the real model and save each reply; a prompt's effect shows only there.

    .venv/Scripts/python.exe evaluation/boundary/run_probes.py baseline
    .venv/Scripts/python.exe evaluation/boundary/run_probes.py unseen U       # only probes starting with U
    .venv/Scripts/python.exe evaluation/boundary/run_probes.py retest K3,N1   # or with any of these

Writes results/<label>.jsonl. Uses the test database (<DB_NAME>_test) with the frozen data, so the
project's own data and accounts are not touched, and OPENAI_API_KEY and OPENAI_MODEL from .env, as
the server does. Cases from cases.json must be in the dev split: the holdout stays unrun until the
system freezes.
"""

import json
import sys
from contextlib import closing
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from agent import build_agent
from config import env
from mock_db import create_database, empty_storage, set_listing
from profiles import UserProfiles
from response import render_steps
from sessions import serializer


def load_probes() -> list[dict]:
    """The probes, with those naming a dev case filled in from cases.json."""
    data = json.loads((ROOT / "evaluation" / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in (data["cases"] if "cases" in data else data.values())}
    probes = []
    for probe in json.loads((HERE / "probes.json").read_text(encoding="utf-8"))["probes"]:
        if "case" in probe:
            case = cases[probe["case"]]
            if case["split"] != "dev":
                raise SystemExit(f"{probe['case']} is in the holdout, which must not run before the freeze.")
            turns = [turn["user"] for turn in case["turns"]]
            probe = {**probe, "id": probe["case"], "messages": [*case["preconditions"].get("prior_turns", []), *turns]}
        probes.append(probe)
    return probes


def run(graph, connection, probe: dict) -> dict:
    """One probe in its own conversation; the last message's reply is the one to judge."""
    config = {"configurable": {"thread_id": f"probe-{probe['id']}"}}
    changed = probe.get("set_title")
    if changed:
        (original,) = connection.query("SELECT title FROM listings WHERE listing_id = %s", (changed["listing_id"],))
        set_listing(connection, changed["listing_id"], title=changed["title"])
    try:
        for message in probe["messages"]:
            result = graph.invoke({"message": message, "user_id": f"probe-{probe['id'].lower()}"}, config=config)
    finally:
        if changed:
            set_listing(connection, changed["listing_id"], title=original["title"])
    return {
        "reply": result["response"],
        "tools": [line.split("(", 1)[0].removeprefix("[tool] ") for line in result["trace"] if line.startswith("[tool]")],
        "guard": [line for line in result["trace"] if line.startswith("[guard]")],
        "steps": render_steps(result["trace"], result.get("response_language", "zh")),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    if not env("OPENAI_API_KEY") or not env("OPENAI_MODEL"):
        raise SystemExit("Set OPENAI_API_KEY and OPENAI_MODEL in .env first")
    output = HERE / "results" / f"{sys.argv[1]}.jsonl"
    output.parent.mkdir(exist_ok=True)
    wanted = tuple(sys.argv[2].split(",")) if len(sys.argv) == 3 else ""
    probes = [probe for probe in load_probes() if probe["id"].startswith(wanted)]
    model = ChatOpenAI(model=env("OPENAI_MODEL"), api_key=env("OPENAI_API_KEY"), use_responses_api=True)
    with closing(create_database()) as connection, output.open("w", encoding="utf-8") as file:
        graph = build_agent(connection, model, MemorySaver(serde=serializer()), profiles=UserProfiles(empty_storage()))
        for number, probe in enumerate(probes, 1):
            row = {key: probe[key] for key in ("id", "group", "expected", "messages")}
            try:
                row.update(run(graph, connection, probe))
            except Exception as error:
                row["error"] = f"{type(error).__name__}: {error}"
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            file.flush()
            print(f"[{number}/{len(probes)}] {probe['id']} {row.get('error') or row['tools']}", flush=True)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
