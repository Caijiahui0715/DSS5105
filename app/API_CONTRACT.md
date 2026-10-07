# Draft API Contract v0.1 — Pending Backend and Agent Confirmation

There is currently **no HTTP API** in the inspected repository. Everything
below is a proposal. Python repository/service functions are not HTTP endpoints.
HttpRentalApi/HttpAgentApi are safe placeholders and never send requests.

## Shared response conventions

IDs are strings. Decimal rent/area become JSON numbers with an agreed precision.
SQL NULL becomes JSON null; unknown categories remain `"unknown"`. Dates are
YYYY-MM-DD. Collection timestamps have no confirmed timezone; do not append Z.
Review flags are arrays, including empty arrays. Source evidence is associated
by listing ID. Errors: `{ "error": { "code": "...", "message": "..." } }`.
UI mapping is centralized in BackendMapper, not pages.

The current static adapter uses V2 active-at-snapshot records, excludes removed
IDs and joins historical V1 evidence/metadata. Future responses must include
original and refreshed monthly rent separately, snapshot status and checked_at,
coordinate source and error, and evidence timestamps. The UI uses an explicit
effective price for budget checks; it does not overwrite the original value.
V2 cooking/pets aliases are normalized while original fields remain available.
Missing route data is not filled from listing-to-MRT walking times.

## Proposed endpoints

| Method and path | Request | Response |
|---|---|---|
| GET /listings | max_budget, district_code, rental_scope, property_type, min_bedrooms, limit, cursor | listings array plus optional next_cursor |
| GET /listings/{id} | text listing ID | listing, district, metadata, source_evidence; 404 if absent |
| POST /candidates | hard requirements | pass / needs_confirmation / fail arrays of listing + evaluation |
| POST /recommendations | requirements, preferences, priorities | recommendation array plus unknown factors and provenance |
| POST /chat | conversation_id, message, requirements, preferences | message, extracted requirements, clarification, recommendations |
| GET/PUT /profile | authenticated user / editable requirements and preferences | user profile, requirements, preferences |
| GET/POST/DELETE /favorites | user context / listing_id | saved listing IDs and saved timestamps |
| GET/POST /conversations | user context / optional title | conversation IDs, messages and timestamps |
| GET /conversations/{id} | user context | conversation and recommendation snapshot |
| POST /commute | listing_id, verified origin, specific NUS destination, mode, departure_time | duration, route, checked_at, source, verification status |

No identity, route or persistence endpoints exist today. Server authentication,
authorization, pagination, endpoint versioning and transport security must be
agreed before integration; no client-side demo identity is authoritative.

## Candidate request / response example

```json
{"max_budget":2500,"rental_scope":"room","min_bedrooms":1,"limit":200}
```

```json
{
  "pass": [],
  "needs_confirmation": [{
    "listing": {"listing_id":"500253628","bedrooms":null},
    "evaluation": {
      "listing_id":"500253628",
      "status":"needs_confirmation",
      "checks":{"min_bedrooms":{"status":"needs_confirmation","reason":"Bedroom count is not confirmed."}}
    }
  }],
  "fail": []
}
```

The listing example is intentionally abbreviated; actual details must carry the
full 30-field V1 record, district name and metadata. Existing services prefilter
by budget and limit before classifying, so their fail bucket is not a complete
inventory of all rejected listings. Search SQL excludes unknown matching values;
candidate classification is the appropriate contract for three-state UX.

## Proposed recommendation / Agent payloads

```json
{
  "conversation_id":"session-id",
  "message":"Find a room under SGD 2500 near NUS.",
  "requirements":{"max_budget":2500,"rental_scope":"room","min_bedrooms":null},
  "preferences":{"districts":["D05"],"max_commute_minutes":40}
}
```

```json
{
  "message":"Candidate summary grounded in returned data.",
  "extracted_requirements":{"max_budget":2500,"rental_scope":"room"},
  "clarification":null,
  "recommendations":[{
    "listing_id":"500253628","rank":1,"suitability_score":45,
    "constraint_status":"pass","match_level":"Potential demo match",
    "match_reasons":[],"tradeoffs":[],"unknown_factors":[],
    "is_demo_score":true,"provenance":{"score":"mock"}
  }]
}
```

This is a schema illustration, not a verified score or API result. Agent facts
must come from retrieval/route tools, not free-text invention. B's Backend must
own authoritative constraints, including the agreed handling of contradictory
evidence. C's Agent must cite evidence and ask for missing requirements. Review
flags remain distinct from requirement status until a specific policy is agreed.

## Integration sequence

1. B confirms listing, joins, nullable values and candidate semantics.
2. C confirms chat context, extraction and recommendations.
3. Implement HTTP transport and mapper against fixtures, with explicit errors.
4. Configure endpoints outside code; never expose DB credentials.
5. Replace the adapter factory without rewriting view components.
6. Validate unknown/contradictory facts, serialization and route provenance.
