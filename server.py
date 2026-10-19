"""Web demo for several users: accounts, each user's own conversations, and progress while the agent works.

    python server.py            # http://127.0.0.1:8000, this computer only
    python server.py --lan      # also reachable from the same Wi-Fi (plain HTTP)
    python server.py --port=8080

The reply itself still arrives in one piece at the end of a turn: the fact check decides whether it
can be shown, so only progress lines are sent while the agent works (Server-Sent Events).
"""

import json
import logging
from datetime import date
from functools import cache
import socket
import sys
import threading
from collections import defaultdict
from pathlib import Path
from queue import Queue
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from psycopg import OperationalError
from pydantic import BaseModel, ValidationError

from accounts import TOKEN_LIFETIME, AccountError, Accounts
from agent import build_agent, memory_switch, opening_state, profile_update, save_to_profile
from decision import EVIDENCE_PATH
from faculties import FACULTIES, find_faculty
from group_db import UNAVAILABLE
from models import SearchPreferences
from profiles import EXCLUDED, SHORTLIST, UserProfiles, merged
from response import criteria_items, render_profile_opening, render_steps
from sessions import Storage
from tools import check_listing_url, get_listings_by_ids, load_listings

COOKIE = "rental_session"
PAGE = Path(__file__).parent / "static" / "index.html"
_WAITING = {"zh": "这段对话的上一条消息还在处理，已排队", "en": "Waiting for the previous message in this conversation"}
_FAILED = "处理这条消息时出错，请稍后重试。"


class Credentials(BaseModel):
    username: str
    password: str
    # Optional at sign-up; changeable later under "我的学院".
    faculty: str | None = None


class FacultyIn(BaseModel):
    faculty: str | None


class MessageIn(BaseModel):
    message: str
    # The frontend's interface language, for messages that do not show one ("1000", "D05"); otherwise
    # the reply follows the message.
    language: Literal["zh", "en"] | None = None


class ShortlistIn(BaseModel):
    listing_id: str


class NewConversationIn(BaseModel):
    # The language of the opening message when the conversation starts from the long-term profile.
    language: Literal["zh", "en"] = "zh"


class ProfileIn(BaseModel):
    # Criteria changed on the Profile page: each one's new value, or null to drop it.
    changes: dict[str, Any]


class MemoryIn(BaseModel):
    on: bool


class SaveProfileIn(BaseModel):
    # True only after the user agreed to switch long-term memory on, when it is off.
    switch_on: bool = False


def create_app(listings, model, storage: Storage, checkpointer, listing_checker=check_listing_url) -> FastAPI:
    accounts = Accounts(storage)
    profiles = UserProfiles(storage)
    agent = build_agent(listings, model, checkpointer, listing_checker=listing_checker, profiles=profiles)
    _account_listings_once(storage, profiles, agent)
    # One turn at a time per conversation; a second message waits for the first.
    locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
    locks_guard = threading.Lock()
    app = FastAPI(title="Singapore Rental Decision Agent")

    @app.exception_handler(OperationalError)
    def database_unavailable(request: Request, error: OperationalError):
        # The pool connects again for the next request. QueryCanceled (a query over the time limit)
        # and PoolTimeout (no free connection) arrive here too; the class name tells them apart.
        logging.warning("database unavailable (%s): %s", type(error).__name__, error)
        return JSONResponse({"detail": UNAVAILABLE}, status_code=503)

    def lock_for(thread_id: str) -> threading.Lock:
        with locks_guard:
            return locks[thread_id]

    def token_of(request: Request) -> str | None:
        # The page sends the cookie; a frontend calling from its own server sends the header.
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        return token.strip() if scheme.lower() == "bearer" and token.strip() else request.cookies.get(COOKIE)

    def current_user(request: Request) -> str:
        user_id = accounts.user_for(token_of(request))
        if not user_id:
            raise HTTPException(401, "请先登录。")
        return user_id

    def owned(user_id: str, thread_id: str) -> None:
        # The same answer whether the conversation is missing or someone else's.
        if not storage.owns(user_id, thread_id):
            raise HTTPException(404, "找不到这段对话。")

    def config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def recorded_faculty(name: str | None) -> str | None:
        faculty = find_faculty(name or "")
        if name and not faculty:
            raise HTTPException(400, "请从列表里选择学院。")
        return faculty and faculty["name"]

    @app.get("/", include_in_schema=False)
    def page():
        return FileResponse(PAGE)

    @app.get("/api/faculties")
    def faculties():
        return [
            {key: faculty[key] for key in ("name", "zh", "campus", "code", "latitude", "longitude")}
            for faculty in FACULTIES
        ]

    @app.get("/api/options")
    def options():
        """Choices for a frontend's sign-up and criteria forms: the districts that have listings, and property types."""
        rows = load_listings(listings)
        districts = sorted({(row["district_code"], row["district"]) for row in rows if row.get("district_code")})
        return {
            "districts": [{"code": code, "name": name} for code, name in districts],
            "property_types": sorted({row["property_type"] for row in rows if row.get("property_type")}),
        }

    @app.post("/api/register")
    def register(body: Credentials, response: Response):
        faculty = recorded_faculty(body.faculty)
        try:
            user_id = accounts.register(body.username, body.password)
        except AccountError as error:
            raise HTTPException(400, str(error)) from error
        if faculty:
            profiles.set_faculty(user_id, faculty)
        return login(body, response)

    @app.post("/api/login")
    def login(body: Credentials, response: Response):
        try:
            user_id, token = accounts.login(body.username, body.password)
        except AccountError as error:
            raise HTTPException(400, str(error)) from error
        # HttpOnly: scripts on the page cannot read the token.
        response.set_cookie(COOKIE, token, max_age=int(TOKEN_LIFETIME.total_seconds()), httponly=True, samesite="lax")
        return me(user_id)

    @app.post("/api/token")
    def token(body: Credentials):
        """Sign in for a client on its own server, such as the Streamlit frontend; send Authorization: Bearer <token>."""
        try:
            user_id, token = accounts.login(body.username, body.password)
        except AccountError as error:
            raise HTTPException(400, str(error)) from error
        return {"token": token, "token_type": "bearer", **me(user_id)}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        accounts.logout(token_of(request))
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/me")
    def me(user_id: str = Depends(current_user)):
        return {"username": user_id, "faculty": profiles.faculty(user_id)}

    @app.put("/api/me/faculty")
    def set_faculty(body: FacultyIn, user_id: str = Depends(current_user)):
        """Every conversation uses the new faculty for commute times from the next message on."""
        profiles.set_faculty(user_id, recorded_faculty(body.faculty))
        return me(user_id)

    def profile_view(user_id: str) -> dict:
        """The long-term profile as the Profile page shows it, whether memory is on or off."""
        consent = profiles.consent(user_id)
        kept = profiles.profile(user_id) or {}
        saved, sources = kept.get("preferences", {}), kept.get("sources", {})
        return {
            "memory": memory_switch(consent),
            "saved_on": kept.get("saved_on"),
            "preferences": saved,
            "sources": sources,
            "budget": kept.get("budget"),
            "items": criteria_items(saved, sources),
            # What a new conversation's first message says while memory is on.
            "opening": {language: render_profile_opening(saved, language) for language in ("zh", "en")} if consent and saved else None,
        }

    @app.get("/api/me/profile")
    def long_term_profile(user_id: str = Depends(current_user)):
        return profile_view(user_id)

    @app.put("/api/me/profile")
    def edit_profile(body: ProfileIn, user_id: str = Depends(current_user)):
        """Change criteria on the Profile page. Saving switches memory on for a user who never decided;
        while it is off the profile cannot be changed."""
        if profiles.consent(user_id) is False:
            raise HTTPException(409, "长期记忆已关闭，打开后才能修改长期资料。")
        unknown = sorted(set(body.changes) - set(SearchPreferences.model_fields) | set(body.changes) & {"faculty"})
        if unknown:
            raise HTTPException(400, f"不认识的条件：{', '.join(unknown)}")
        kept = profiles.profile(user_id) or {}
        saved = kept.get("preferences", {})
        wanted = {field: value for field, value in {**saved, **body.changes}.items() if value is not None}
        try:
            values = SearchPreferences.model_validate(wanted).model_dump(mode="json", exclude_defaults=True)
        except ValidationError as error:
            raise HTTPException(400, f"条件不对：{error.errors()[0]['msg']}") from error
        changes = {field: values.get(field) for field in SearchPreferences.model_fields if values.get(field) != saved.get(field)}
        if changes:
            source = {"via": "profile", "date": date.today().isoformat()}
            # A budget typed on the page is a monthly amount in SGD.
            profiles.save(user_id, merged(kept, changes, {field: source for field in changes}, None))
        return profile_view(user_id)

    @app.put("/api/me/memory")
    def switch_memory(body: MemoryIn, user_id: str = Depends(current_user)):
        """Switch long-term memory on or off; what is kept stays either way."""
        profiles.set_consent(user_id, body.on)
        return profile_view(user_id)

    @app.delete("/api/me/profile")
    def delete_profile(user_id: str = Depends(current_user)):
        """Delete the kept criteria; the switch, listings and faculty stay."""
        profiles.delete_profile(user_id)
        return profile_view(user_id)

    def account_listings(user_id: str) -> dict:
        shortlist, excluded = profiles.listings(user_id)
        return {"shortlist": shortlist, "excluded": excluded}

    @app.get("/api/me/listings")
    def my_listings(user_id: str = Depends(current_user)):
        """The account's shortlisted and excluded listings, shared by all its conversations."""
        return account_listings(user_id)

    @app.post("/api/me/shortlist")
    def add_to_shortlist(body: ShortlistIn, user_id: str = Depends(current_user)):
        found = [listing["listing_id"] for listing in get_listings_by_ids(listings, [body.listing_id.strip()])]
        if not found:
            raise HTTPException(404, "找不到这套房源。")
        # A shortlisted listing is no longer excluded, as in chat.
        profiles.mark(user_id, found, SHORTLIST)
        return account_listings(user_id)

    @app.delete("/api/me/shortlist/{listing_id}")
    def remove_from_shortlist(listing_id: str, user_id: str = Depends(current_user)):
        profiles.unmark(user_id, [listing_id], SHORTLIST)
        return account_listings(user_id)

    @app.delete("/api/me/excluded/{listing_id}")
    def restore_listing(listing_id: str, user_id: str = Depends(current_user)):
        """Searches show an excluded listing again."""
        profiles.unmark(user_id, [listing_id], EXCLUDED)
        return account_listings(user_id)

    @app.get("/api/listings")
    def listings_page(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user_id: str = Depends(current_user),
    ):
        """Every listing in the data, in pages; the same fields the agent ranks with."""
        rows = load_listings(listings)
        return {"total": len(rows), "listings": rows[offset:offset + limit]}

    @app.get("/api/listings/{listing_id}")
    def listing_details(listing_id: str, user_id: str = Depends(current_user)):
        """One listing with its full source record (page text, photos, field evidence), where recorded."""
        found = get_listings_by_ids(listings, [listing_id])
        if not found:
            raise HTTPException(404, "找不到这套房源。")
        return {"listing": found[0], "source_evidence": _source_records().get(listing_id)}

    @app.get("/api/conversations")
    def conversations(user_id: str = Depends(current_user)):
        return storage.threads(user_id)

    @app.post("/api/conversations")
    def new_conversation(body: NewConversationIn | None = None, user_id: str = Depends(current_user)):
        """While long-term memory is on, the conversation starts from the kept criteria, with a first
        message saying so in body.language."""
        thread_id = storage.new_thread(user_id)
        if opening := opening_state(profiles, user_id, (body or NewConversationIn()).language):
            agent.update_state(config(thread_id), opening, as_node="finalize")
        return {"id": thread_id, "title": ""}

    def criteria(user_id: str, values: dict) -> dict:
        """A conversation's saved criteria for a page: the values, where each came from, labels, and
        what saving them would change in the long-term profile."""
        preferences = values.get("preferences")
        saved = preferences.model_dump(mode="json", exclude_defaults=True) if preferences else {}
        sources = values.get("preference_sources") or {}
        return {
            "preferences": saved,
            "sources": sources,
            "items": criteria_items(saved, sources),
            "profile_changes": profile_update(profiles, user_id, values)[1] if preferences else [],
        }

    @app.get("/api/conversations/{thread_id}")
    def conversation(thread_id: str, user_id: str = Depends(current_user)):
        """What a frontend needs to reopen a conversation: the saved criteria, the latest search's
        listings (as in each reply's recommendations) and the account's shortlist."""
        owned(user_id, thread_id)
        values = agent.get_state(config(thread_id)).values
        return {
            "id": thread_id,
            **criteria(user_id, values),
            "recommendations": values.get("last_recommendations"),
            "shortlist": profiles.listings(user_id)[0],
        }

    @app.get("/api/conversations/{thread_id}/profile")
    def profile_changes_of(thread_id: str, user_id: str = Depends(current_user)):
        """What saving this conversation's criteria would change in the long-term profile."""
        owned(user_id, thread_id)
        values = agent.get_state(config(thread_id)).values
        rows = profile_update(profiles, user_id, values)[1] if values.get("preferences") else []
        return {"memory": memory_switch(profiles.consent(user_id)), "changes": rows}

    @app.post("/api/conversations/{thread_id}/profile")
    def save_conversation_profile(thread_id: str, body: SaveProfileIn, user_id: str = Depends(current_user)):
        """Save the criteria this conversation changed into the long-term profile; what other
        conversations or the Profile page changed stays. While memory is off, only with switch_on."""
        owned(user_id, thread_id)
        with lock_for(thread_id):
            if profiles.consent(user_id) is False:
                if not body.switch_on:
                    raise HTTPException(409, "长期记忆已关闭，要打开并保存吗？")
                profiles.set_consent(user_id, True)
            values = agent.get_state(config(thread_id)).values
            if not values.get("preferences"):
                return {"changes": [], "profile": profile_view(user_id)}
            rows, base = save_to_profile(profiles, user_id, values)
            # Later saves from here count changes from what was just saved; the question is not asked again.
            agent.update_state(config(thread_id), {"profile_base": base, "memory_asked": True}, as_node="finalize")
        return {"changes": rows, "profile": profile_view(user_id)}

    @app.get("/api/conversations/{thread_id}/messages")
    def history(thread_id: str, user_id: str = Depends(current_user)):
        owned(user_id, thread_id)
        values = agent.get_state(config(thread_id)).values
        traces = values.get("reply_traces") or {}
        language = values.get("response_language", "zh")
        items = []
        for message in values.get("messages", []):
            if isinstance(message, HumanMessage):
                items.append({"role": "user", "text": message.content})
            elif isinstance(message, AIMessage) and message.id in traces:
                # Only final replies have a saved trace; tool calls and rejected drafts are skipped.
                items.append({"role": "assistant", "text": message.content, "steps": render_steps(traces[message.id], language)})
        return items

    @app.post("/api/conversations/{thread_id}/messages")
    def send(thread_id: str, body: MessageIn, user_id: str = Depends(current_user)):
        owned(user_id, thread_id)
        text = body.message.strip()
        if not text:
            raise HTTPException(400, "消息不能为空。")
        events: Queue = Queue()

        def run():
            # Runs apart from the response, so a closed page does not cut a turn short.
            lock = lock_for(thread_id)
            if not lock.acquire(blocking=False):
                events.put(("progress", _WAITING))
                lock.acquire()
            try:
                storage.touch(thread_id, text)
                final = {}
                turn = {"message": text, "user_id": user_id, "reply_language": body.language}
                for mode, chunk in agent.stream(turn, config(thread_id), stream_mode=["custom", "values"]):
                    if mode == "custom" and "progress" in chunk:
                        events.put(("progress", chunk["progress"]))
                    elif mode == "values":
                        final = chunk
                reply = final["messages"][-1]
                steps = render_steps(final["reply_traces"][reply.id], final.get("response_language", "zh"))
                # recommendations: the listings a search showed this turn, with each one's status, for listing cards.
                events.put((
                    "reply",
                    {
                        "text": final["response"],
                        "steps": steps,
                        "recommendations": final.get("recommendations"),
                        **criteria(user_id, final),
                        # The agent can change the shortlist in chat too; read again, since the
                        # page or another conversation may have changed it during the turn.
                        "shortlist": profiles.listings(user_id)[0],
                    },
                ))
                storage.touch(thread_id, text)
            except OperationalError as error:
                logging.warning("database unavailable in %s (%s): %s", thread_id, type(error).__name__, error)
                events.put(("error", {"message": UNAVAILABLE}))
            except Exception:
                logging.exception("turn failed in %s", thread_id)
                events.put(("error", {"message": _FAILED}))
            finally:
                lock.release()
                events.put(None)

        threading.Thread(target=run, daemon=True).start()

        def stream():
            while (event := events.get()) is not None:
                name, data = event
                yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    def delete_thread(thread_id: str) -> None:
        with lock_for(thread_id):
            checkpointer.delete_thread(thread_id)
            storage.forget_thread(thread_id)

    @app.delete("/api/conversations/{thread_id}")
    def delete_conversation(thread_id: str, user_id: str = Depends(current_user)):
        owned(user_id, thread_id)
        delete_thread(thread_id)
        return {"ok": True}

    @app.delete("/api/me/data")
    def delete_my_data(response: Response, user_id: str = Depends(current_user)):
        """Every conversation, the kept profile, listings and the faculty; the account stays and must sign in again."""
        for thread in storage.threads(user_id):
            delete_thread(thread["id"])
        profiles.delete(user_id)
        accounts.sign_out_everywhere(user_id)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    return app


def _account_listings_once(storage: Storage, profiles: UserProfiles, agent) -> None:
    """Shortlists and exclusions used to be kept per conversation (and in long-term profiles); once,
    they become the account's. Profiles come first, then conversations from the least to the most
    recently active, so each listing ends up as the latest of them left it."""
    name = "account_listings"
    if profiles.migrated(name):
        return
    kept = [(user_id, profile) for user_id, profile in profiles.all_profiles()]
    states = [
        (user_id, agent.get_state({"configurable": {"thread_id": thread_id}}).values)
        for thread_id, user_id in storage.all_threads()
        # demo.py --workflow keeps the baseline's own conversations, in another state shape.
        if not user_id.endswith("@workflow")
    ]
    for user_id, values in [*kept, *states]:
        profiles.mark(user_id, values.get("shortlisted_listing_ids", []), SHORTLIST)
        profiles.mark(user_id, values.get("excluded_listing_ids", []), EXCLUDED)
    profiles.finish_migration(name)


@cache
def _source_records() -> dict[str, dict]:
    try:
        records = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {str(record["listing_id"]): record for record in records}


def _lan_address() -> str:
    # Opening a UDP socket sends nothing; it only reveals which local address routes outward.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        except OSError:
            return socket.gethostbyname(socket.gethostname())


def main() -> None:
    import uvicorn
    from langchain_openai import ChatOpenAI

    from config import env
    from group_db import open_database
    from sessions import open_storage

    sys.stdout.reconfigure(encoding="utf-8")
    flags = set(sys.argv[1:])
    port = int(next((flag.split("=", 1)[1] for flag in flags if flag.startswith("--port=")), 8000))
    if flags - {"--lan"} - {flag for flag in flags if flag.startswith("--port=")}:
        raise SystemExit("Usage: python server.py [--lan] [--port=8000]")
    if not env("OPENAI_API_KEY") or not env("OPENAI_MODEL"):
        raise SystemExit("Set OPENAI_API_KEY and OPENAI_MODEL in .env first")

    # An unreachable database stops here with what to fix.
    database = open_database()
    storage, checkpointer = open_storage(database)
    # Reasoning models such as gpt-5.x only accept function tools on the Responses API.
    model = ChatOpenAI(model=env("OPENAI_MODEL"), api_key=env("OPENAI_API_KEY"), use_responses_api=True)
    app = create_app(database, model, storage, checkpointer)
    host = "0.0.0.0" if "--lan" in flags else "127.0.0.1"
    print(f"打开 http://127.0.0.1:{port}")
    if "--lan" in flags:
        print(f"同一 Wi-Fi 下可访问 http://{_lan_address()}:{port}（明文 HTTP，只在信任的网络里使用）")
    try:
        uvicorn.run(app, host=host, port=port)
    finally:
        database.close()


if __name__ == "__main__":
    main()
