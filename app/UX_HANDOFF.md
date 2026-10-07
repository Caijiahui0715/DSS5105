# UX handoff — NUS Rental Decision Agent

## Goal and users

Help NUS students and staff translate rental needs into an understandable set
of options, compare trade-offs and inspect original source facts. This student
demo uses real static listings and explicitly labelled illustrative behaviour.

## Page inventory

- Login/Register: English demo forms; no real identity verification; passwords
  removed on submission. Registration cannot skip budget, rental scope or the
  bedroom choice. Soft preferences can be left blank or explicitly skipped.
  Demo-account entry is available.
- Home: persistent narrow Home/Favorites/Profile icon rail; collapsible session
  history; chat-only center; fixed upper map and lower compact listing panel.
  Prompts live in the empty listing panel, not in the chat stream.
- Recommendations: eligible listings, status filter, text search, pagination,
  rent/demo-match/demo-commute sorting, favorites and three-way comparison.
- Rental Map: V2 geocoded/inferred markers and all-listing selector fallback;
  selected card/marker/selector updates the same session selection.
- Profile: editable identity, hard constraints and soft preferences.
- Favorites: session-only saved options, details, map link and comparison.
- Conversation History: new conversation and reopening session history.
- Evaluation: three agreed scenarios plus ambiguous/unanswerable scenarios,
  expected constraints, five dimensions and four pending baselines.

## Journey and constraints

Enter demo → describe needs → clarify requirements → retrieve real listings →
classify hard constraints → rank using transparent demo scoring → inspect
map/details/evidence → save/compare → adjust Profile → revisit conversation.

Budget, scope and minimum bedrooms are hard requirements. Unknown hard facts
remain Needs confirmation. Fail precedes Needs confirmation precedes Pass in
constraint aggregation. Fail listings are excluded from recommendations.
MRT, district, furnishing, lifestyle and commute are soft preferences. They
do not silently tighten/relax hard requirements. Profile saves update the active
conversation; other conversations retain their own requirement context.

## Visual language and components

Wide light layout, navy headings/actions, white cards, 12px radii and restrained
borders. Streamlit info/warning/error elements provide textual status, not colour
alone. Native widgets drive all logic. Custom CSS covers layout and visual style
only. Shared cards/details/comparison/map prevent separate selection states.

## States and provenance

- Loading: cached source-data spinner and Agent processing status.
- Empty: first chat, no recommendations, no favorites, no selected listing.
- Warning: unknown constraints, data review flags, unverified availability.
- Errors: invalid auth/profile input, missing data, disconnected future APIs,
  missing photos and unavailable map.
- Source/derived/mock/unavailable: compact explanations, detailed provenance
  audit; demo scoring, commute and Agent are explicitly labelled. Listing
  positions come from V2; inferred coordinates and errors are labelled.

Never call all static listings mock. Unknown values stay unknown; images are
optional. Bathroom counts are not privacy evidence. Tenant counts are not
capacity. MRT minutes are not NUS travel times. Empty flags are not certification.
No measured evaluation statistics are displayed.

## Responsive and accessibility notes

Desktop targets approximately 1440×900. Narrow columns stack in document order;
use the regular navigation and explicit map/listing selectors. Long source text
lives in expanders. The UI does not claim a custom mobile bottom sheet or native
bottom navigation. Streamlit reruns may reset scroll position. Map interaction
depends on iframe/network behaviour and is backed by native selectboxes.

Global navigation exposes only Home, Favorites and Profile. Secondary views
remain implemented but are not added to the rail. New conversations clear the
selected listing and map markers; reopening a conversation restores its results.
The upper/lower panels have stable bounds and internal scrolling, not pagination.

Native forms have labels and keyboard-accessible actions. Focus outlines remain
visible. Status text complements colour; map home/train/graduation-cap icons
distinguish listing/MRT/NUS types. No autoplay or decorative motion. Reduced
motion is respected. Source-image captions identify their origin. Full keyboard
and screen-reader behaviour in Folium depends on the embedded component; use
the native selector fallback.

## Integration and limitations

Session state is temporary: no user DB, browser localStorage or true login.
HttpRentalApi/HttpAgentApi are deliberately disconnected placeholders. B owns
the future authoritative Backend, source serialization and persistent records.
C owns the real Agent, tools, context and grounded explanations. Listing
coordinates already use V2 data. Route evidence must replace demo commute
estimates separately. Active link status is only valid at the recorded snapshot.

## Presentation flow and screenshot guidance

1. Enter the demo account and explain real facts versus demo estimates.
2. Use the SGD 2,500 prompt; inspect extracted requirements and top cards.
3. Select a card, then its map marker/selector; show linked details/provenance.
4. Save three options and compare advertised rent, unknowns and demo commute.
5. Change budget in Profile and observe refreshed eligible results.
6. Start a conversation, reopen the previous one, and show session-only history.
7. Open Evaluation and explain pending results and baselines honestly.

Capture the desktop Home, comparison, provenance details and Evaluation for
slides after checking layout. Future stretch goals: conversation indexing,
language switching, contract review and rental progress management.
