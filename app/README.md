# NUS Rental Decision Agent

A Streamlit-only DSS5105 student demonstration for NUS students and staff.
Search less, decide better. This app supports rental decisions using the latest
V2 snapshot (376 active-at-snapshot advertisements checked on 2026-10-04).
It is not a property marketplace or production Agent.

## Local setup and startup

Python 3.12 and uv are required. From Windows PowerShell:

```powershell
cd E:\NUS_DSS\DSS5105-group-project
$env:UV_CACHE_DIR = "$env:LOCALAPPDATA\uv\cache"
$env:UV_LINK_MODE = "copy"
uv sync --project app
uv run --project app streamlit run app/streamlit_app.py
```

Open http://localhost:8501 and choose **Continue with demo account**, or fill
the English Login/Register demo forms. Neither form verifies identity.
Registration requires an explicit monthly budget, rental scope and minimum
bedroom choice (including an explicit No minimum option). Soft preferences
are optional; skipping them does not apply default district, MRT or commute preferences.
Passwords are removed from widget/session state immediately on submission and
are never persisted, logged, or sent to a Backend. Do not use a real password.

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
Profile. Home has a collapsible conversation-history panel, a chat-only center,
and two fixed right-hand panels: map above and compact listing card below.
Recommendations and requirement summaries do not appear in the chat column.
The map has no markers until recommendations exist; the listing panel starts
empty with suggested prompts. Its content scrolls internally without pagination.
Existing secondary views remain implemented for later integration, outside the
primary navigation. Login/Register remain the demo entry screen.

Views → shared components and session state → domain model → RentalApi/AgentApi.
`StaticRentalApi` and `MockAgentApi` power the demo. `BackendMapper` owns
snake_case-to-camelCase conversion. HTTP adapters are safe placeholders and do
not send requests. Static loading uses `st.cache_data`; application state uses
`st.session_state`. `st.set_page_config` is the first Streamlit command.

## Real data and provenance

Six existing files are read directly using paths resolved from the loader:

- `output-final-delivery/rental_data_v2.csv`: authoritative current listing
  fields, refreshed prices, snapshot status, coordinates and nearby features.
- `removed_listings.csv`: explicit exclusion set, including 217 removed records
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
Of 376 positions, 16 are inferred from POI evidence and labelled approximate,
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

## Demo ranking and Agent

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

Profiles, favorites, comparisons, selected listings and conversations exist
only in the current Streamlit session. Refresh, WebSocket disconnection, server
restart or logout can reset them. There is no database or localStorage
persistence. Logout clears session-owned state. Compare up to three listings.

Source photos are optional, read into memory with a timeout, never saved to
disk, and replaced by a placeholder on failure. OpenStreetMap tiles and Folium
external assets need internet; no paid key is required. If the map cannot load,
the listing selectors remain available. Source links may expire. Narrow-screen
columns stack; this is not a native mobile app or a custom bottom-navigation UI.

## Verification

```powershell
uv run --project app pytest app/tests
```

Tests cover V2 joins, removed listings, refreshed-price budget boundaries,
label normalization, preservation, coordinates, images, three-state constraints,
score ranges, separation, Agent queries, demo login password disposal, all
pages, favorites, the compare limit, profile updates and conversation reopening.
AppTest exercises Python/widget behaviour; browser checks separately verify
layout and custom map rendering. Evaluation shows planned scenarios and
baselines only, not fabricated final performance statistics.

## Backend integration for B / Agent integration for C

See `API_CONTRACT.md`. Agree endpoints before implementing HTTP adapters.
Implement mapping for JSON-safe decimals, dates, arrays, missing values and
quality metadata. B's candidate classification becomes authoritative. Implement
server-owned authentication/profile/favorites/history as separate integration
work. C implements requirement extraction, tool calls, explanations and context.
Keep unknown facts and source evidence in responses. Replace adapter selection
via `RENTAL_DATA_MODE` / `AGENT_MODE`; HTTP mode currently reports an explicit
not-connected error. No secrets or endpoints are hardcoded.

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

## Future scope

Live routes, persistent identity and records, production Agent,
conversation indexing, language switching, contract review and rental progress
management are future work. No measured quality, latency or satisfaction is
claimed by this demo.
