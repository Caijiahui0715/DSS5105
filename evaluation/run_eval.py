"""Run the agent on the evaluation cases with the real model and save every turn for score.py.

    .venv/Scripts/python.exe evaluation/run_eval.py dev1
    .venv/Scripts/python.exe evaluation/run_eval.py dev1-retest --only A01,G02
    .venv/Scripts/python.exe evaluation/run_eval.py final --runs 3
    .venv/Scripts/python.exe evaluation/run_eval.py holdout --holdout   # once, after the system freezes
    .venv/Scripts/python.exe evaluation/run_eval.py b4-dev --system workflow   # baseline B4, the fixed workflow

Writes results/<label>.jsonl: a header with the version, model and data hashes, then one row per
turn. A label already there runs only the cases not yet finished without an error, under a header of
its own; score.py keeps the latest rows of a case. Each case gets its own user and conversation, so
nothing carries over. Uses the test database (<DB_NAME>_test) with the frozen data and OPENAI_API_KEY
and OPENAI_MODEL from .env.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from agent import build_agent
from config import env
from graph import build_graph
from mock_db import create_database, empty_storage
from profiles import UserProfiles
from response import NOT_SEARCHED, render_steps
from sessions import serializer

RESULTS = ROOT / "evaluation" / "results"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def header(model: str, split: str, system: str = "B5_agent") -> dict:
    def git(*args):
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True).stdout

    diff = git("diff", "HEAD", "--", "*.py")
    return {
        "meta": {
            "system": system,
            "split": split,
            "commit": git("rev-parse", "--short", "HEAD").decode().strip(),
            # Changes not committed yet, so a run can still be traced to the code it used.
            "uncommitted_py_sha256": hashlib.sha256(diff).hexdigest() if diff else None,
            "model": model,
            "listings_sha256": sha256(ROOT / "output-final-delivery" / "rental_data_v2.csv"),
            "commute_sha256": sha256(ROOT / "commute_faculty.csv"),
            "cases_sha256": sha256(ROOT / "evaluation" / "cases" / "cases.json"),
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    }


def run_turn(graph, config: dict, user: str, message: str) -> dict:
    started = time.perf_counter()
    result = graph.invoke({"message": message, "user_id": user}, config=config)
    recommendations = result.get("recommendations") or {}
    preferences = result.get("preferences")
    return {
        "reply": result["response"],
        "preferences": preferences.model_dump(mode="json", exclude_defaults=True) if preferences else {},
        "preview": recommendations.get("preview"),
        "shown": [{"listing_id": item["listing_id"], "status": item["status"]} for item in recommendations.get("listings", [])],
        "comparison_ids": (result.get("comparison") or {}).get("listing_ids"),
        "tools": [line.split("(", 1)[0].removeprefix("[tool] ") for line in result["trace"] if line.startswith("[tool]")],
        # Asking the user first is a decision, not a failed call.
        "tool_errors": sum(" -> error: " in line and f" -> error: {NOT_SEARCHED}" not in line for line in result["trace"] if line.startswith("[tool]")),
        "guard": [line for line in result["trace"] if line.startswith("[guard]")],
        "trace": result["trace"],
        "steps": render_steps(result["trace"], result.get("response_language", "zh")),
        "seconds": round(time.perf_counter() - started, 1),
    }


def run_workflow_turn(graph, config: dict, faculty: str | None, message: str) -> dict:
    """B4, the fixed workflow (graph.py): it shows its top 3 strict matches, then the listings to confirm."""
    started = time.perf_counter()
    result = graph.invoke({"message": message, "faculty": faculty}, config=config)
    preferences = result.get("preferences")
    ranked = result.get("ranked_listings") or []
    confirm = result.get("confirm_listings") or []
    trace = result.get("trace") or []
    return {
        "reply": result["response"],
        "preferences": preferences.model_dump(mode="json", exclude_defaults=True) if preferences else {},
        "preview": None,
        "shown": [{"listing_id": item["listing"]["listing_id"], "status": "match"} for item in ranked[:3]]
                 + [{"listing_id": item["listing"]["listing_id"], "status": "needs_confirmation"} for item in confirm],
        "comparison_ids": None,
        "tools": [],
        "tool_errors": 0,
        "guard": [line for line in trace if line.startswith("[guard]")],
        "trace": trace,
        "seconds": round(time.perf_counter() - started, 1),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("label")
    parser.add_argument("--only", default="", help="comma-separated case IDs")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--holdout", action="store_true", help="run the holdout: once only, after the system freezes")
    parser.add_argument("--system", choices=("agent", "workflow"), default="agent",
                        help="agent (B5, default) or the fixed workflow baseline in graph.py (B4)")
    args = parser.parse_args()
    workflow = args.system == "workflow"
    if not env("OPENAI_API_KEY") or not env("OPENAI_MODEL"):
        raise SystemExit("Set OPENAI_API_KEY and OPENAI_MODEL in .env first")
    split = "holdout" if args.holdout else "dev"
    data = json.loads((ROOT / "evaluation" / "cases" / "cases.json").read_text(encoding="utf-8"))
    cases = [case for case in (data["cases"] if "cases" in data else data.values()) if case["split"] == split]
    if args.only:
        wanted = args.only.split(",")
        known = {case["id"] for case in cases}
        if missing := [case_id for case_id in wanted if case_id not in known]:
            raise SystemExit(f"Not in the {split} split: {', '.join(missing)}")
        cases = [case for case in cases if case["id"] in wanted]

    output = RESULTS / f"{args.label}.jsonl"
    output.parent.mkdir(exist_ok=True)
    done, failed = set(), set()
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "meta" in row:
                continue
            attempt = (row["id"], row["run"])
            if "error" in row:
                failed.add(attempt)
            if row["last_turn"]:
                (done.discard if attempt in failed else done.add)(attempt)
                failed.discard(attempt)
    model_name = env("OPENAI_MODEL")
    # The workflow calls the model without tools, as demo.py --workflow does.
    model = ChatOpenAI(model=model_name, api_key=env("OPENAI_API_KEY"), use_responses_api=not workflow)
    with closing(create_database()) as connection, output.open("a", encoding="utf-8") as file:
        file.write(json.dumps(header(model_name, split, "B4_workflow" if workflow else "B5_agent"), ensure_ascii=False) + "\n")
        storage = empty_storage()
        profiles = UserProfiles(storage)
        graph = (build_graph(connection, model, MemorySaver(serde=serializer())) if workflow
                 else build_agent(connection, model, MemorySaver(serde=serializer()), profiles=profiles))
        for run in range(1, args.runs + 1):
            for number, case in enumerate(cases, 1):
                if (case["id"], run) in done:
                    continue
                user = f"eval-{args.label}-{case['id']}-{run}".lower()
                config = {"configurable": {"thread_id": user}}
                if (faculty := case["preconditions"].get("faculty")) and not workflow:
                    profiles.set_faculty(user, faculty)
                prior = case["preconditions"].get("prior_turns", [])
                turns = [(message, True) for message in prior] + [(turn["user"], False) for turn in case["turns"]]
                turn_number = 0
                for index, (message, is_prior) in enumerate(turns):
                    turn_number += not is_prior
                    row = {"id": case["id"], "category": case["category"], "run": run, "turn": 0 if is_prior else turn_number,
                           "last_turn": index == len(turns) - 1, "user": message}
                    try:
                        row.update(run_workflow_turn(graph, config, faculty, message) if workflow
                                   else run_turn(graph, config, user, message))
                    except Exception as error:
                        row["error"] = f"{type(error).__name__}: {error}"[:500]
                    file.write(json.dumps(row, ensure_ascii=False) + "\n")
                    file.flush()
                    print(f"[{number}/{len(cases)}] {case['id']} turn {row['turn']} {row.get('error') or row['tools']} {row.get('seconds', '')}s", flush=True)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
