# Connecting the front end to the back end: list of changes (for Fangyue)

The page layout, styles and interactions are kept exactly as you designed them; what changed is where the data comes from. By default, accounts, listings, chat, recommendations, commutes, conversation history and favourites all come from the back end, `server.py` (repository root). With `AGENT_MODE=mock` it is still the original offline demo, and your tests run in that mode.

## How to run

```powershell
.\.venv\Scripts\python.exe .\server.py                     # terminal 1: back end
uv run --project app streamlit run app/streamlit_app.py    # terminal 2: front end
uv run --project app pytest app/tests                      # tests (offline mode, no back end needed)
```

Front-end settings live in `app/.env` (not committed): `BACKEND_URL` (default `http://127.0.0.1:8000`), optionally `DEMO_USERNAME` / `DEMO_PASSWORD` ("Continue with demo account" appears only when they are set), and optionally `AGENT_MODE=mock`.

## Changes on each page (when connected to the back end)

- **Sign in / sign up**: username (3–20 letters, digits or underscores, case-insensitive, and not already taken) + password (at least 8 characters, entered twice when signing up); signing up can set an NUS faculty (commutes are computed to it). The hard conditions and preferences on the sign-up form are kept and sent to the agent as the first message after submitting, so the reply shows how the agent understood them. "Remember me on this device" is ticked by default and keeps the sign-in token in a cookie for 7 days; signing out deletes the cookie and revokes the token. There is an English / 中文 switch at the top.
- **Home**: chat goes to the real agent; a sent message appears at once, with the agent's progress below it, and each reply can be expanded to show "how this reply was made". The list on the right is the listings the agent showed in this search; it stays unchanged on a turn with no search. The graduation cap on the map is the user's faculty. The map at the top right fills its whole frame (a fixed 350 px high, with the listing panel below taking the remaining height). The line "V2 data locations · inferred positions approximate" above the map was removed; when a position is an inferred approximation, each marker's tooltip still says so (the check for that line in `scripts/verify_browser.py` now checks the map instead). Conversations in the sidebar are saved to the account and are still there after signing in again; there is also a language switch at the bottom of the sidebar.
- **Cards / details**: the 0–100 score is no longer shown. They show the rank, the status (matches / to be confirmed), which conditions are still missing when to be confirmed, the monthly rent, MRT, the commute to the faculty, and the link check result.
- **Favourites**: this is the agent's shortlist in the current conversation; the agent can see it too, so the user can ask it to compare them directly. The comparison table is display only.
- **Profile**: the faculty is saved straight to the account; the criteria form sends only the changed fields to the agent as one message (for example "Please update my search criteria: a monthly rent of at most SGD 2,000."), then returns to the home page to show the reply. Only one district can be chosen, because the agent searches one district at a time.
- **Recommendations / Rental Map / Conversation History / Evaluation**: the files are all still there but are not loaded when connected to the back end (they use the offline demo's scoring). They work as before in offline mode, for you to connect later.

## Files

Added:

- `adapters/backend_client.py`: every call to the back end (standard-library HTTP, Bearer token, Server-Sent Events for replies).
- `domain/criteria.py`: the conditions the agent saves ↔ the form values, and turning form changes into a message.
- `content/i18n.py`, `content/labels.py`: the interface language (`t(English, Chinese)`) and Chinese names for data values.
- `state/cookies.py`: the remember-me cookie.
- `tests/test_criteria.py`: tests for the criteria message.
- `tests/test_frontend_client.py` at the repository root: calls `server.py` through `backend_client.py`, and fails if the two sides' interfaces disagree.

Changed:

- `adapters/configuration.py`: connects to the back end by default, offline with `AGENT_MODE=mock`; reads `app/.env`. `RENTAL_DATA_MODE` is no longer used.
- `adapters/http_rental_api.py`, `http_agent_api.py`: the placeholders were replaced with real implementations.
- `domain/models.py`: `Recommendation.score` may be empty, and `facts` (the agent's information about the listing) was added; `AgentResponse` gained `steps`, `shortlist` and `preview`.
- `state/session_store.py`: after sign-in, loads conversations from the back end, reads messages and criteria when opening one, keeps favourites on the back end, and revokes the token on sign-out.
- `streamlit_app.py`: automatic sign-in from the cookie, routing to only the three main pages (plus the other four offline), and error messages in the interface language.
- `views/auth.py`, `home.py`, `profile.py`, `favorites.py`, `components/*`: the behaviour above, and interface text in English and Chinese.
- `domain/provenance.py`: `display()` turns only codes such as `fully_furnished` into words; station names, addresses and dates are shown as they are (before, `capitalize()` turned them into "Cc26 pasir panjang mrt").
- `domain/location.py`: location notes in English and Chinese.
- `tests/conftest.py`: sets `AGENT_MODE=mock`; none of your original tests changed.
- `README.md`, `API_CONTRACT.md`: the relevant parts were rewritten for the current interfaces.

Unchanged: `data/*`, `domain/recommendation.py`, `adapters/static_rental_api.py`, `mock_agent_api.py`, `backend_mapper.py`, the other four pages, `scripts/verify_browser.py`, `UX_HANDOFF.md` and `FILE_MANIFEST.md` (the last two describe the offline demo).

## Good to know

- Remember-me was first going to use the CookieManager of `extra-streamlit-components`, but every cookie read or write made the page rerun and interrupted the agent reply on screen, so the cookie is written with Streamlit's own `components.html` instead. `extra-streamlit-components` in `pyproject.toml` is no longer needed and can be removed with `uv remove --project app extra-streamlit-components`. Page scripts can read this cookie (it is not HttpOnly), an acceptable trade-off for a demo project.
- Clicking another button while the agent is replying makes the page rerun and interrupts the display, but the back end finishes the turn; the next page run reloads the conversation from the back end. While a reply has not arrived, the conversation shows a notice with a Refresh button.
- The agent replies in the language of each message (Chinese to a Chinese message); the interface language is used only when a message shows no language (for example just `1000`).
- Before display, chat messages escape `$` (otherwise Streamlit treats "S$2,999 … S$3,100" as a formula) and keep line breaks (the agent's replies put each listing's rent, MRT and commute on separate lines).
- The "conditions to be confirmed" and link notes on cards are in the language of the turn in which the agent searched; after switching language they change only with the next search.
- I could not install a real Streamlit here, so the page flows were run with a simplified stand-in; please run `uv run --project app pytest app/tests` locally, then connect to the back end and click through once.

## 2026-10-10: lease and costs

The listing data was replaced with the new `rental_data_v2.csv` of 10/9 (327 listings, with a new `lease_term` column; `removed_listings.csv` has 266).

- **Sign up / profile**: when connected to the back end there is a new "Lease length you will sign" drop-down (any, 6 months, 1 year, 2 years); like the other conditions, a change is sent to the agent as a message (for example "Please update my search criteria: a 6-month lease."). `RentalRequirements` gained `lease_months` (default `None`), and `domain/criteria.py` the matching text. The offline demo does not show this field, because the demo scoring does not filter by lease.
- **Cards / details**: show "Lease: at least 2 years" (`lease_text()` in `components/listing_card.py`, with the text in `lease_term_label()` in `content/i18n.py`); a listing with no lease stated shows "not stated".
- **Chat**: when the user asks about costs, the agent's reply includes a cost breakdown in a fixed format; the front end needs to do nothing.
- **Tests changed because of the data update**: `test_source_loader.py` (327 listings, 266 removed, 11 inferred coordinates), `test_v2_snapshot.py` (327), `test_data_contract.py` (1 listing with furnishing not stated), `test_recommendation.py` (now finds a listing with furnishing not stated instead of always using the first). In the offline demo's `data/demo_enrichment.py`, 500253628 was taken down and replaced with 500252277, and the place in `test_app_smoke.py` that picks that listing was updated to match.
- I could run only the tests that do not need a real Streamlit (39 of 40 pass; the remaining one lacks `folium`); please run `test_app_smoke.py` locally.

## 2026-10-10: back end on PostgreSQL only

No front-end code changed, and the offline demo (`AGENT_MODE=mock`) is not affected. When connecting to the back end:

- The back end's listings, accounts and conversations are now all in PostgreSQL. The first time, run `.\.venv\Scripts\python.exe .\setup_database.py` once in the repository root, then start `server.py`. If PostgreSQL is not running, the back end will not start and says what to check.
- The old `sessions.sqlite` is no longer used, and its accounts were not moved: demo accounts (for example `demo_user`) must be registered again in the app with the same username and password; `app/.env` needs no change.
- If the database disconnects during a chat, that turn's error message says the database is temporarily unreachable and to try again later (an `error` event in the stream); other endpoints return HTTP 503 with the same `detail`. The front end can show the error as before, and the next message reconnects automatically.
