# API contract — what this app calls on the agent backend

The backend is `server.py` at the repository root (FastAPI). The repository
README's "给前端的接口" section is the full description; this is the frontend's
view of it. Every call goes through `adapters/backend_client.py`, and
`tests/test_frontend_client.py` (repository root) runs that client against the
server, so a change on either side that breaks the other fails there.

## Conventions

- Base URL: `BACKEND_URL`, default `http://127.0.0.1:8000`.
- After signing in, every request sends `Authorization: Bearer <token>`. A 401
  means the token expired or was revoked: the app signs out and asks to sign in.
- Errors are `{"detail": "..."}` with a 4xx status; the messages are Chinese and
  the app shows English ones for the known messages (`content/i18n.py`).
- IDs are strings. Missing values are `null`; unknown categories stay `"unknown"`.
- Listing fields are the backend's snake_case names; `BackendMapper` turns them
  into the camelCase facts the views use. `rent_monthly_sgd` is the rechecked
  rent and `rent_monthly_sgd_card` the advertised one. `lease_term` is the
  advert's lease term as written ("1 year", "2 years", "Flexible", "Short
  Term", "Prefer not to say" or `null`), the shortest lease the landlord accepts.

## Calls

| Method and path | Used for | Response |
|---|---|---|
| GET /api/faculties | sign-up and Profile faculty choice, map anchor (no sign-in) | `[{name, zh, campus, code, latitude, longitude}]` |
| GET /api/options | sign-up and Profile districts and property types (no sign-in) | `{districts: [{code, name}], property_types}` |
| POST /api/register | create an account `{username, password, faculty}` | account; then POST /api/token |
| POST /api/token | sign in `{username, password}` | `{token, token_type, username, faculty}` |
| GET /api/me | sign in from the remember-me cookie | `{username, faculty}` |
| PUT /api/me/faculty | Profile `{faculty}` (null clears it) | `{username, faculty}` |
| POST /api/logout | sign out; revokes the token | `{ok}` |
| GET /api/listings?limit=200&offset=N | map and selectors, in pages | `{total, listings}` |
| GET /api/listings/{id} | listing details with photos and page text | `{listing, source_evidence}`; 404 when gone |
| GET /api/conversations | the conversation panel after sign-in | `[{id, title, created_at, updated_at}]` |
| POST /api/conversations | at a conversation's first message `{language}`; while long-term memory is on it starts from the long-term profile, with a first message in that language | `{id, title}` |
| GET /api/conversations/{id} | reopening a conversation | `{id, preferences, sources, items, profile_changes, recommendations, shortlist}` |
| GET /api/conversations/{id}/messages | reopening a conversation | `[{role, text, steps?}]` |
| POST /api/conversations/{id}/messages | a message `{message, language}`; `language` is the interface language, used when the message shows none | Server-Sent Events, below |
| GET /api/conversations/{id}/profile | Home "Save to long-term profile": what saving would change | `{memory, changes: [{field, label, before, after}]}` |
| POST /api/conversations/{id}/profile | saving it `{switch_on}` (true only after the user agreed to switch memory on; 409 while it is off otherwise) | `{changes, profile}` |
| GET /api/me/profile | Profile page, and a new conversation before its first message | `{memory, saved_on, preferences, sources, budget, items, opening}` |
| PUT /api/me/profile | Profile form `{changes: {criterion: value or null}}`; 409 while memory is off | the profile, as GET |
| PUT /api/me/memory | Profile memory switch `{on}` | the profile, as GET |
| DELETE /api/me/profile | Profile "Delete long-term profile" | the profile, as GET |
| GET /api/me/listings | the account's favorites and exclusions | `{shortlist, excluded}` |
| POST /api/me/shortlist | Save `{listing_id}`; an excluded listing is no longer excluded | `{shortlist, excluded}` |
| DELETE /api/me/shortlist/{listing_id} | Unsave | `{shortlist, excluded}` |
| DELETE /api/me/excluded/{listing_id} | Profile "Restore" | `{shortlist, excluded}` |
| DELETE /api/me/data | Profile "Delete all my data"; signs out everywhere | `{ok}` |

## A reply

`POST .../messages` answers with Server-Sent Events: any number of
`event: progress` with `data: {"zh": ..., "en": ...}` while the agent works,
then one `event: reply` (or `event: error` with `{"message"}`):

```json
{
  "text": "the reply, in the message's language (the interface language when the message shows none)",
  "steps": ["how the reply was made", "..."],
  "preferences": {"max_price_sgd": 1800, "rental_scope": "room", "lease_months": 12},
  "sources": {"max_price_sgd": {"quote": "预算1800", "date": "2026-10-19"}},
  "items": [{"field": "max_price_sgd", "label": {"zh": "每月最高预算", "en": "maximum monthly budget"},
             "value": {"zh": "S$1,800", "en": "S$1,800"}, "source": {"quote": "预算1800", "date": "2026-10-19"}}],
  "profile_changes": [{"field": "max_price_sgd", "label": {"zh": "每月最高预算", "en": "maximum monthly budget"},
                       "before": {"zh": "S$2,500", "en": "S$2,500"}, "after": {"zh": "S$1,800", "en": "S$1,800"}}],
  "shortlist": ["500253628"],
  "recommendations": {
    "preview": false,
    "listings": [{
      "status": "match",
      "position": 1,
      "listing_id": "500253628",
      "title": "Chwee Chian View",
      "rent_monthly_sgd": 1850,
      "mrt_station": "CC26 Pasir Panjang MRT",
      "mrt_minutes": 9,
      "commute_minutes_to_faculty": 23,
      "commute_mode": "transit",
      "lease_term": "1 year",
      "link_status": "active",
      "link_note": "active",
      "unknown_conditions": [],
      "unknown_condition_labels": []
    }]
  }
}
```

`recommendations` is `null` when the turn did not search; the app then keeps
the listings it already shows. `status` is `match` (meets every condition) or
`needs_confirmation` (the listing does not state some conditions, named in
`unknown_condition_labels`). `preview: true` means a what-if search that left
the saved criteria unchanged. `preferences` holds only the criteria that are
set; `domain/criteria.py` maps them onto the criteria form (`lease_months` is the
lease length the user will sign, in months), and back with `to_backend` for the
Profile page. `sources` says where each criterion came from (the user's words and
date, or `{"via": "profile", "date"}` for a Profile page edit); `items` lists every
set criterion with its label and value in both languages, for the "Other criteria"
list. `profile_changes` is what saving this conversation's criteria would change in the
long-term profile (Home shows the count above the criteria panel). `shortlist` is the
account's, shared by every conversation. Cost estimates (total rent, stamp
duty, deposit, what is paid at signing) arrive as part of `text`.
