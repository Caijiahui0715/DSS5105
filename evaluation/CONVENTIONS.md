# Evaluation conventions (confirmed 2026-11-05)

`gold.py` computes the gold answers strictly by this page. The system and the evaluation scripts both follow it, and Evaluation.pdf refers to it. Any change to a rule means running `gold.py` again and recording the change at the end of this page.

The 4 items marked as open in the draft ("below X", number of occupants, "near NUS" and "entire apartment") were confirmed on 2026-11-05 and apply as written below.

## 1. Data snapshot

- Listings: `output-final-delivery/rental_data_v2.csv`, the final data frozen on 2026-11-02: 369 listings, all with `scrape_status=active`. The 61 listings taken down are in `removed_listings.csv` and **are not part of the evaluation**. Recommending a listing that was taken down counts as a violation.
- Commutes: `commute_faculty.csv`, the OneMap public-transport cache: 369 listings × 16 faculties, departing at 08:30 on a weekday. The evaluation reads only the cache and never calls OneMap online.
- `gold.py` writes the file hashes into the metadata of `gold/gold_answers.json`; system runs record the same hashes.

## 2. Three outcomes

For each hard condition, a listing gets one of three outcomes:

| Outcome | Meaning |
|---|---|
| pass | The data clearly meets the condition |
| unknown | The data does not say, or says something that cannot be judged |
| fail | The data clearly does not meet the condition |

Overall: one fail makes the listing **excluded**; no fail but at least one unknown makes it **needs_confirmation**; only a listing that passes everything is **confirmed**. The system may present only confirmed listings as matches. Listings that need confirmation may be shown, but must be marked as needing confirmation, with the unknown item named (each listing in `gold_answers.json` has its `unknown_fields`).

## 3. Rules for each field

| Condition | pass | unknown | fail |
|---|---|---|---|
| Budget `max_price_sgd` | Rent ≤ limit | Rent missing | Rent > limit |
| Whole unit / room `rental_scope` | Same | — | Different |
| Room type `room_type` | Same | `room_unspecified`, `unknown` | Another room type, or not a room |
| District `district_code` | Same | — | Different |
| Gender `tenant_gender=female` | `female_only`, `no_restriction` | `unknown` | `male_only` |
| Furniture `furnished_required` | Fully furnished, partially furnished, `furnished_unspecified` | `unknown` | `unfurnished` |
| Fully furnished `furnishing_level=full` (B07) | `fully_furnished` | `furnished_unspecified`, `unknown` | Partially furnished, `unfurnished` |
| Can cook `cooking_required` | `light_cooking`, `cooking_any_cooking` | `unknown`, `cooking_prefer_not_to_say` | `cooking_not_allowed`, `not_allowed` |
| Full cooking `cooking_level=full` | `cooking_any_cooking` | `unknown`, `cooking_prefer_not_to_say` | `light_cooking`, cooking not allowed |
| Air-conditioning | `yes` | `unknown` | `no` (not in the data) |
| Minimum bedrooms, bathrooms | ≥ minimum | Missing | < minimum |
| Walk to MRT (minutes or metres) | Nearest station is open and ≤ limit | Nearest station is not open (under construction or status unknown) and ≤ limit; or the value is missing | Value > limit |
| Commute to faculty | Cached minutes ≤ limit | Not in the cache | > limit |
| Property type | In the list after normalising | — | Not in the list |
| Minimum area, number of food places | ≥ minimum | Missing | < minimum |
| Can sign for N months `lease_months` | The listing's shortest lease ≤ N (Flexible counts as 0, Short Term as 1, 1 year as 12, 2 years as 24) | Missing, `Prefer not to say` | Shortest lease > N |
| Landlord does not live in | `no` | `unknown` | `yes` |
| Pets allowed | `pets_allowed` | `unknown` | `no_pets` |
| Private bathroom | `yes` | `unknown` | `no` (not in the data) |

Other conventions:

- **Which rent column**: `rent_monthly_sgd_now` (the latest recorded advertised price), falling back to `rent_monthly_sgd` only when it is missing. Cases such as H01 and H02 must answer with both columns.
- **"below / under X"** means ≤ X, the same as "no more than X".
- **MRT stations under construction**: the data gives only the nearest station, whether or not it is open. When the nearest station is under construction, the nearest open station can only be farther away: if the value is already over the limit the outcome is fail, otherwise unknown.
- **Number of occupants `occupant_count`** is not a filter, because whole-unit listings have no field for how many people may live there. It is used only to test the system's parsing (the must_not of A06 and A07 forbids reading 4 people as 4 bedrooms).
- **Normalising property types**: lower case, with spaces and hyphens replaced by underscores (`HDB Flat` → `hdb_flat`, `Condominium` → `condominium`).
- **Listings with inferred coordinates**: for listings with `coord_source=pg_poi_inferred`, commute and MRT values can be off by about 165 m. The gold answer uses them as usual, but `top_3` carries `coord_source`, to be taken into account in failure analysis.

## 4. How requests are read

- **"near NUS" / "close to NUS"** (G01 and G05, turn 1): no number is given, so it is a soft preference used only for ranking (commute first), not a filter.
- **Faculty**: as set in each case (Faculty of Science for A03, A10 and C04; School of Computing for A04, A06 and C05). G01, G02 and G05 had no faculty; ranking by commute needs a destination, so they use Faculty of Science (the same as the account used when the agent ran them). This is written in each case's `preconditions`.
- **"entire apartment"** (G04): read as a whole unit, with no limit on property type. In everyday Singapore usage, "apartment" often means any flat.
- **G04 turn 2, "a shared unit is fine too"**: the whole unit / room limit is removed, so both whole units and rooms count.
- **G05**: neither turn says whole unit or room, so neither is required.
- **"this property" in categories E and F**: a set-up turn, "Tell me about listing 500074659.", is sent first and not scored; the questions after it refer to that listing.

## 5. Ranking

- Listings are ranked strictly in the order of the priorities the user states (lexicographic); with no stated priority, by rent, lowest first. If rent is not among the user's priorities, it is used as the last tie-breaker, and after that listing_id.
- Mapping: price → rent, lowest first; commute → commute to the set faculty, shortest first; mrt → minutes to walk to the MRT, fewest first; space → area, largest first; food_places → food places within 1 km, most first. Missing values go last.
- Only confirmed listings are ranked. `top_3` is the gold answer's top three.
- **When the user states no priority**, the system balances MRT distance and (when there is a budget) rent, rather than sorting by rent. The `top_3` of such cases is still by rent, lowest first, kept as a reference for baseline B1, and **is not used to judge the system's order**; how well the system ranks in these cases is judged by the human ranking (metric 7). When the user states priorities, the system must rank exactly as this section says.

## 6. Relaxation (category C)

Only the one field the case names (`relaxation_field`) is relaxed. Among listings that pass every other condition and fail only this one, the gold answer finds the smallest change that turns at least one listing into confirmed and records it as `relaxation.minimum_relaxed_value`; `ladder` gives the first few relaxed values with the cumulative number of listings. When the MRT condition is relaxed, the nearest station must be open.

When `relaxation_field` is a list (C08), each field is tried on its own and gets its own result; fields are not compared to decide which change is "smaller".

If changing this one field is not enough (for example C06), the gold answer records `single_field_relaxation_available=false` and lists which other single condition, if dropped, would give results (`other_single_field_drops`).

## 7. Change log

| Date | What changed | Confirmed by |
|---|---|---|
| 2026-11-05 | First draft; all gold answers recomputed on the frozen data of 11/02 | — |
| 2026-11-05 | The 4 open items confirmed as drafted; no rule changed | Caijiahui0715 |
| 2026-11-05 | Added the "fully furnished" rule used by B07; category C can test several relaxation fields at once (C08) | Caijiahui0715 |
| 2026-11-06 | Section 5: in cases where the user states no priority, the system's order is not judged. The calculation in `gold.py` did not change, so the gold answers are the same | Caijiahui0715 |
