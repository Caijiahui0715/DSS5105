"""Web demo for several users: accounts, each user's own conversations, and progress while the agent works.

    python server.py            # http://127.0.0.1:8000, this computer only
    python server.py --lan      # also reachable from the same Wi-Fi (plain HTTP)
    python server.py --port=8080

The reply itself still arrives in one piece at the end of a turn: the fact check decides whether it
can be shown, so only progress lines are sent while the agent works (Server-Sent Events).
"""

import json
import logging
import socket
import sys
import threading
from collections import defaultdict
from pathlib import Path
from queue import Queue

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from accounts import TOKEN_LIFETIME, AccountError, Accounts
from agent import build_agent
from decision import load_source_evidence
from faculties import FACULTIES, find_faculty
from profiles import UserProfiles
from response import render_steps
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


def create_app(listings, model, storage: Storage, checkpointer, listing_checker=check_listing_url) -> FastAPI:
    accounts = Accounts(storage)
    profiles = UserProfiles(storage)
    agent = build_agent(listings, model, checkpointer, listing_checker=listing_checker, profiles=profiles)
    # Listings read from the group's PostgreSQL are rebuilt when the data there changes.
    refresh = getattr(listings, "refresh", None) or (lambda: False)
    # One turn at a time per conversation; a second message waits for the first.
    locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
    locks_guard = threading.Lock()
    app = FastAPI(title="Singapore Rental Decision Agent")

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
        return [{"name": faculty["name"], "zh": faculty["zh"], "campus": faculty["campus"]} for faculty in FACULTIES]

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

    @app.get("/api/listings")
    def listings_page(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user_id: str = Depends(current_user),
    ):
        """Every listing in the data, in pages; the same fields the agent ranks with."""
        refresh()
        rows = load_listings(listings)
        return {"total": len(rows), "listings": rows[offset:offset + limit]}

    @app.get("/api/listings/{listing_id}")
    def listing_details(listing_id: str, user_id: str = Depends(current_user)):
        """One listing with the listing page's original wording behind its fields, where recorded."""
        refresh()
        found = get_listings_by_ids(listings, [listing_id])
        if not found:
            raise HTTPException(404, "找不到这套房源。")
        return {"listing": found[0], "source_evidence": load_source_evidence().get(listing_id)}

    @app.get("/api/conversations")
    def conversations(user_id: str = Depends(current_user)):
        return storage.threads(user_id)

    @app.post("/api/conversations")
    def new_conversation(user_id: str = Depends(current_user)):
        return {"id": storage.new_thread(user_id), "title": ""}

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
                refresh()
                storage.touch(thread_id, text)
                final = {}
                for mode, chunk in agent.stream(
                    {"message": text, "user_id": user_id}, config(thread_id), stream_mode=["custom", "values"]
                ):
                    if mode == "custom" and "progress" in chunk:
                        events.put(("progress", chunk["progress"]))
                    elif mode == "values":
                        final = chunk
                reply = final["messages"][-1]
                steps = render_steps(final["reply_traces"][reply.id], final.get("response_language", "zh"))
                # recommendations: the listings a search showed this turn, with each one's status, for listing cards.
                events.put(("reply", {"text": final["response"], "steps": steps, "recommendations": final.get("recommendations")}))
                storage.touch(thread_id, text)
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
        """Every conversation, the kept profile and the faculty; the account stays and must sign in again."""
        for thread in storage.threads(user_id):
            delete_thread(thread["id"])
        profiles.delete(user_id)
        accounts.sign_out_everywhere(user_id)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    return app


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
    from group_db import open_listings
    from sessions import open_storage

    sys.stdout.reconfigure(encoding="utf-8")
    flags = set(sys.argv[1:])
    port = int(next((flag.split("=", 1)[1] for flag in flags if flag.startswith("--port=")), 8000))
    if flags - {"--lan"} - {flag for flag in flags if flag.startswith("--port=")}:
        raise SystemExit("Usage: python server.py [--lan] [--port=8000]")
    if not env("OPENAI_API_KEY") or not env("OPENAI_MODEL"):
        raise SystemExit("Set OPENAI_API_KEY and OPENAI_MODEL in .env first")

    # Listings first: with AGENT_DB=postgres an unreachable database stops here with a clear message.
    listings = open_listings()
    storage, checkpointer = open_storage()
    # Reasoning models such as gpt-5.x only accept function tools on the Responses API.
    model = ChatOpenAI(model=env("OPENAI_MODEL"), api_key=env("OPENAI_API_KEY"), use_responses_api=True)
    app = create_app(listings, model, storage, checkpointer)
    host = "0.0.0.0" if "--lan" in flags else "127.0.0.1"
    print(f"打开 http://127.0.0.1:{port}")
    if "--lan" in flags:
        print(f"同一 Wi-Fi 下可访问 http://{_lan_address()}:{port}（明文 HTTP，只在信任的网络里使用）")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
