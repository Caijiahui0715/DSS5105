# NUS Rental Decision Agent

The Streamlit frontend of the DSS5105 rental decision agent, for NUS students
and staff. Search less, decide better. It is not a property marketplace.

It runs in one of two modes:

- **With the agent backend** (default): accounts, listings, the agent's replies
  and recommendations, commute times to the user's faculty, conversations and
  favorites all come from `server.py` at the repository root, which reads the
  project's PostgreSQL (set it up as in "Getting started" in the root `README.md`).
- **Offline demo** (`AGENT_MODE=mock`): the original demonstration with static
  V2 files, a scripted demo Agent, demo scores and demo commute estimates. No
  backend and no real accounts. The tests run in this mode.

## Local setup and startup

Python 3.12 and uv are required. From Windows PowerShell, in the repository root:

```powershell
$env:UV_CACHE_DIR = "$env:LOCALAPPDATA\uv\cache"
$env:UV_LINK_MODE = "copy"
uv sync --project app
.\.venv\Scripts\python.exe .\server.py                     # terminal 1: the agent backend
uv run --project app streamlit run app/streamlit_app.py    # terminal 2: this app
```

Open http://localhost:8501, then sign in or create an account (username of 3–20
letters, digits or underscores, not already taken, case-insensitive; password
of at least 8 characters, typed twice at sign-up; optionally your NUS faculty,
which commute times are measured to). Registration still asks
for the monthly budget, rental scope and minimum bedroom choice, the lease
length you will sign (any by default), and optional soft preferences; they are sent to the agent as the first message, so its reply
shows what it understood. **Remember me on this device** keeps the sign-in token
in a browser cookie for 7 days (readable by page scripts, unlike the backend
page's HttpOnly cookie); signing out deletes it and revokes the token.

Settings live in the environment or `app/.env` (ignored by Git; copy
`app/.env.example`, and see `USER_GUIDE.md` in the repository root):

```
BACKEND_URL=http://127.0.0.1:8000   # where server.py listens (the default)
DEMO_USERNAME=demo_user             # optional: shows "Continue with demo account",
DEMO_PASSWORD=...                   # signed in as this account (register it first; everyone shares it)
AGENT_MODE=mock                     # optional: the offline demo instead of the backend
```

The interface is in English by default; the login page and the conversation
panel switch it to Chinese. The agent replies in the language of each message
(Chinese for a Chinese message); the interface language decides only when a
message shows none, such as `1000` or `D05`. The interface follows the same way:
a message in Chinese switches it to Chinese and one in English back to English,
so the listing cards and the map match the reply, until the user picks a
language with the switch; that choice then stays for the session.
The backend's account and form errors are in English; the Chinese interface shows
them in Chinese (`BACKEND_ZH` in `content/i18n.py`).

The app is an independent, non-package uv project. Only its environment and
lockfile are managed; the root Python project is unchanged. No Node tooling,
requirements.txt, secrets file, or global installation is used.

If the configured Windows cache is inaccessible, keep the process settings
above but override cache placement within the permitted app directory:

```powershell
uv sync --project app --cache-dir app/.uv-cache
uv run --project app --cache-dir app/.uv-cache streamlit run app/streamlit_app.py
uv run --project app --cache-dir app/.uv-cache pytest app/tests
```

If Python discovery fails, append `--python` with the path to an existing
Python 3.12 executable to `uv sync`. Do not install globally or alter the root
project to work around an environment issue.

## Pages and architecture

The persistent icon rail has exactly three destinations: Home, Favorites and
Profile. Home has a collapsible conversation-history panel (the open conversation,
once started, has a delete button on its row: it asks first, waits while the agent
replies, and a new conversation takes its place; a conversation the agent is
replying in has a spinner, kept after leaving it until the backend has the reply,
checked every 2 seconds), a chat-only center (scrolled to the latest message when
Home is opened from another page or a conversation is opened),
and two fixed right-hand panels: map above and compact listing card below.
Recommendations and requirement summaries do not appear in the chat column.
The map has no markers until recommendations exist; the listing panel starts
empty with suggested prompts. Its content scrolls internally without pagination.
The map's graduation cap is the user's faculty (the NUS anchor without one).
Listing cards show the agent's rank, whether the listing meets every condition
or needs confirmation (and which conditions the listing does not state), rent,
MRT, the commute to the user's faculty (and to the conversation's other destination,
such as a roommate's faculty or a gym, when it has one), the advert's lease term (the shortest
lease the landlord accepts) and the link check; there is no 0–100
score with the backend. Favorites are the agent's shortlist, kept with the account
and shared by every conversation, so the agent can compare them in chat.
Each favorite's card folds "All details" at its end: tables of the rent and home,
location and getting around, furnishing and living, and availability and data,
with every photo; values the system worked out (route times) say "(estimated)" and
missing ones "not stated", and a switch shows the PropertyGuru card text.
"Add to compare" on a listing puts it in the conversation's compare box (up to
three) and asks nothing. On Favorites the box sits above the cards: the favorites
not in it on the left, the box on the right, and listings are dragged between them
(with a mouse from anywhere on a listing, on a touch screen by its handle; Enter or
Space moves the focused one). The box's order is the order of the table's columns.
Compare under the box, or in the Compare bar between the map and the listings on
Home, sends the agent "Compare A and B" from Home, and once the reply is in, its
table opens by itself in a wide window, once: the key differences and the backend's
comparison table. While the box holds the listings last compared, the button opens
their table instead, in the box's order, without asking again; otherwise "Last
comparison" opens the previous one. A comparison asked for in chat fills the box too,
and the bar's button pulses with a "new" mark until opened. The map shows the
compared listings as numbered markers (the table's column numbers) framed together
with the faculty. A button over the map's top-right corner enlarges it in a wide
window (600px high) with the recommended, favorite (red hearts) and compared
listings and the faculty all in view, and a legend; a click on a listing there shows
a card with Save, Add to compare and Details, and the window stays open (closing it
draws the page again). The compare box and its buttons wait while the agent
replies. The comparison belongs to the conversation (the backend keeps the latest,
and the box starts from it when the conversation is opened); the box is built with
Streamlit's own component API (`components/compare_box.py`), without another
package. Offline, Compare fills the Favorites page's table as before. Above the map, a collapsible "This
conversation's criteria" panel shows the conversation's criteria, with where each
came from; its changes are sent to the agent as a message listing only what
changed, and "Save to long-term profile" saves them after showing what changes.
Once a conversation has criteria, a bar above the chat input offers auto-save
(saving the criteria changed in conversations to the long-term profile as they
change) while it is off and long-term memory is not, until the user closes the bar
for good; after switching it on there, the bar says how to stop until closed.
Profile is the long-term profile (the criteria new conversations start from while
long-term memory is on): the memory and auto-save switches, the same criteria form saved directly,
other saved criteria with a button to drop each, deleting the long-term profile,
excluded listings to restore, and deleting all data. The faculty is saved to the
account directly. `components/criteria_panel.py` is the form both pages share.
The secondary views (Recommendations, Rental Map, Conversation History,
Evaluation) remain in `views/` for later work but are only routed in the offline
demo, since they use its demo scoring.

Views → shared components and session state → domain model → RentalApi/AgentApi.
With the backend, `HttpRentalApi` and `HttpAgentApi` call it through
`adapters/backend_client.py` (standard library HTTP, a Bearer token, Server-Sent
Events for replies); `StaticRentalApi` and `MockAgentApi` power the offline demo.
`BackendMapper` owns snake_case-to-camelCase conversion for both.
`domain/criteria.py` turns the agent's saved criteria into form values and form
changes into a message. `content/i18n.py` holds the interface language. Listings
use `st.cache_data` (refreshed every 5 minutes); application state uses
`st.session_state`. `st.set_page_config` is the first Streamlit command.

## Offline demo: real data and provenance

The rest of this section and the next describe the offline demo. With the
backend, the same V2 data comes from `GET /api/listings` (see the repository
README, "API for the front end").

Six existing files are read directly using paths resolved from the loader:

- `output-final-delivery/rental_data_v2.csv`: authoritative current listing
  fields, refreshed prices, snapshot status, coordinates and nearby features.
- `removed_listings.csv`: explicit exclusion set, including 266 removed records
  at the current snapshot. IDs outside V2 are never offered as current listings.
- `rental_data_v1.json`: historical metadata and 28 district names, joined by
  listing ID. Its 600 historical listings do not populate recommendations.
- `source_evidence_v1.json`: source images, advertisement text and extraction
  evidence, joined by listing ID.
- `field_dictionary_v1.json`: historical V1 field contract, not a V2 schema.
- `validation_report.json`: historical V1 integrity report, labelled separately
  from current V2 counts and pending recommendation evaluation.

The files are neither copied nor modified. Only V2 active snapshot listings
outside the removal set are searched. CSV numeric fields become numbers/nulls;
IDs and postcodes stay strings. Cooking and pet labels are normalized explicitly
for UI scoring, while typed original fields remain in `Listing.source_fields`.
The original monthly rent is preserved. Display, budget filtering and scoring
use `rent_monthly_sgd_now`, falling back to the original price with an explicit
label only when the refreshed price is missing. File timestamps and sizes
invalidate cached data; existing conversations are reevaluated on snapshot
changes. Saved IDs outside the active snapshot are shown as unavailable.
Missing or invalid V2 data raises an error rather than reverting to stale V1.
Matching
unknown values are retained as **Needs confirmation**, rather than silently
filled. Listings with failed constraints are excluded from recommendations;
saved listings may still show Fail after requirements change.

Provenance categories: **Source data**, **Derived value**, **Demo estimate**,
and **Not available**. Formatting a number does not change its provenance.
Ranks and constraint checks derive from data; the scoring methodology and Agent
responses are demonstrations. Every source field has a domain provenance entry.
Details provide a compact legend and an expanded provenance audit.

All mock estimates and templates are isolated in `data/demo_enrichment.py`:
an illustrative campus anchor, four demo commute estimates, scoring
weights/calculations and response templates. Listing markers use V2 coordinates.
Of 327 positions, 11 are inferred from POI evidence and labelled approximate,
with recorded errors (including approximate `~500` values) preserved. Other
positions are provided geocodes, not independently verified door locations.
No synthetic listing or MRT positions are added. Selecting an unpositioned
listing shows its details and an explicit unavailable-location notice.

Advertised rent is not total housing cost. Bathrooms do not imply private use.
Tenant labels do not establish occupancy capacity. MRT minutes are not NUS
commute times. Unknown is not false. Empty review flags do not certify facts,
and flags do not prove errors. `active` is link status at the recorded snapshot,
not verified current rental availability. Check and collection timestamps have
no confirmed timezone. Images and extraction evidence are historical V1 records
and may not reflect refreshed advertisement details.
Collection timestamps have no confirmed timezone. Same-address listings are
not automatically deduplicated.

Two source titles are bilingual. Their display titles use exact English
excerpts already present in the originals and are labelled derived. Original
titles remain intact in the domain/source data. Non-English advertisement text
and evidence are not reproduced in the English UI; the source link and files
remain the reference, without fabricated translation.

## Offline demo ranking and Agent

The local adapter mirrors budget, rental scope, and minimum bedroom checks.
Status precedence is Fail → Needs confirmation → Pass. Review flags remain
separate. Pass results precede unconfirmed candidates; neither category implies
real-time verified eligibility.

Weights total 100%: budget 30, demo commute 30, MRT 15, property preference 15,
other known preferences 10. Missing components receive zero points, not full
marks. Property preference is not a property-condition assessment. No condition
facts are fabricated. The numeric score includes a textual match description,
reasons, trade-offs and unknown factors. It is not a trained model or calibrated
probability. The Agent parses obvious budget/scope/bedroom phrases with rules,
uses profile/context defaults transparently, asks clarifications and refuses
unsupported landlord-reliability claims. It never calls an LLM or live scraper.

## Session limits and external resources

With the backend, accounts, conversations, criteria, favorites and each
conversation's latest comparison are kept by the backend; changes to the compare
box not compared yet, and the selected listing, last for the Streamlit session. In the offline demo everything lasts only for the session. Logout
clears session-owned state. Compare up to three listings.

Photos come from the listing's `photos` links in the V2 data (PropertyGuru's
image CDN), or from the V1 source record when a listing has none. A card shows
the first, read into memory with a timeout, never saved to disk, replaced by a
placeholder on failure, and captioned as PropertyGuru's with a link to the
original listing; a favorite's details add every photo as small pictures, which
the browser loads straight from the links. OpenStreetMap tiles and Folium
external assets need internet; no paid key is required. If the map cannot load,
the listing selectors remain available. Source links may expire. Narrow-screen
columns stack; this is not a native mobile app or a custom bottom-navigation UI.

## Verification

```powershell
uv run --project app pytest app/tests
```

These tests run the offline demo (`tests/conftest.py` sets `AGENT_MODE=mock`).
They cover V2 joins, removed listings, refreshed-price budget boundaries,
label normalization, preservation, coordinates, images, three-state constraints,
score ranges, separation, Agent queries, demo login password disposal, all
pages, favorites, the compare limit, profile updates, conversation reopening and
the criteria messages sent to the agent. AppTest exercises Python/widget
behaviour; browser checks separately verify layout and custom map rendering.
The backend side is checked from the repository root:
`tests/test_frontend_client.py` runs this app's backend client against
`server.py`. Evaluation shows planned scenarios and baselines only, not
fabricated final performance statistics.

## Backend integration

`API_CONTRACT.md` lists what this app calls. To add a page that needs backend
data, add the call to `BackendClient`, map it in an adapter, and keep the
offline demo working (or route the page only offline, as the secondary views are).

## Streamlit Community Cloud

1. Use the reviewed frontend branch pushed to GitHub.
2. Open Streamlit Community Cloud.
3. Select this repository.
4. Select the approved deployment branch.
5. Set entry point to `app/streamlit_app.py`.
6. Select Python 3.12.
7. Configure secrets in Cloud settings only if future integrations need them.

The entry-point directory contains its own `uv.lock` and `pyproject.toml`.
Community Cloud checks that directory before the repository root and prioritizes
`uv.lock`: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies
Do not add local secrets files or private docs to the deployment. The six
already tracked delivery JSON/CSV files must be present. Cloud deployment has not
been performed or verified in this task.

A deployed app also needs a reachable backend: set `BACKEND_URL` (and the demo
account, if wanted) as environment variables for the deployment.

## Future scope

Conversation search, contract review and rental progress management are future
work. No measured quality, latency or satisfaction is claimed by this demo.
