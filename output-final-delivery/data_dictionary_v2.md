# rental_data_v2.csv data dictionary

**Version**: v2.3 · **Updated**: 2026-09-18 · **Rows**: 519 active rental listings · **Fields**: 50
**Companion file**: `removed_listings.csv` (74 listings taken down, same fields)

> The counts and coverage figures on this page describe version v2.3 (2026-09-18). The final data frozen on 2026-11-02, which the system and the evaluation use, has 369 active listings (see `evaluation/CONVENTIONS.md`).

---

## 1. Overview

| Item | Details |
|---|---|
| Subject | PropertyGuru Singapore rental listings (mainly D05 and nearby areas such as Bukit Timah, Clementi and West Coast, with a few from other districts) |
| Collection timeline | v1 search pages collected 2026-09-09 → detail pages filled in 2026-09-17 → cleaning of dead or abnormal listings 2026-09-17 to 18 |
| Anti-bot handling and access | Headed Playwright browser + reused Cloudflare session; the data comes from the `__NEXT_DATA__` JSON embedded in each page |
| Coordinates | WGS84 latitude and longitude |
| Cleaning | 74 taken down (removed), 6 rooms with abnormal area dropped, 1 listing that could not be located dropped (traceable in git history) |

**Pipeline**: 600 (v1) → 74 taken down removed → 526 active → 6 with abnormal area removed → 1 (Paradise Island, could not be located) removed → **519**

---

## 2. Fields

### 2.1 Identity and price

| # | Field | Type | Source | Description | Coverage | Typical values / range |
|---|---|---|---|---|---|---|
| 1 | `listing_id` | string | PG | Unique listing ID (primary key) | 100% | — |
| 2 | `title` | string | PG | Listing title (mostly the project name or address) | 100% | — |
| 3 | `listing_url` | string | PG | Listing link, for checking back | 100% | — |
| 4 | `rent_monthly_sgd` | float | v1 | Monthly rent (S$, as collected on 9-9) | 100% | median 4300, [580, 80000] |
| 5 | `rent_price_type` | string | v1 | Kind of price: `asking` / `negotiable` / `starting_from` / `guide_price` | 100% | asking 68% |
| 31 | `rent_monthly_sgd_now` | float | PG 9-17 | Current advertised price; the difference from #4 shows price cuts | 99% | median 4400 |

### 2.2 Layout and area

| # | Field | Type | Source | Description | Coverage | Values |
|---|---|---|---|---|---|---|
| 6 | `rental_scope` | string | PG detail page | Rental type: `room` / `entire_unit`. Declared by the agent who posted it | 99% | entire_unit 348, room 169 |
| 7 | `room_type` | string | PG detail page | Room type: `common_room` / `master_room` / `studio` / `shared_room` / `room_unspecified`. Not applicable to whole units (unknown) | 34% | common 121 |
| 8 | `property_type` | string | PG | Property type: condominium / hdb_flat / apartment / terraced_house / detached_house and others | 100% | condo 273, HDB 100 |
| 9 | `bedrooms` | int | PG | Bedrooms; 0 = studio; not applicable to room rentals (empty) | 68% | median 3 |
| 10 | `bathrooms` | int | PG | Bathrooms | 92% | median 2 |
| 11 | `area_sqm` | float | PG | Area (m²); what it measures is given by #12. Extreme values (> 2000 m²) are luxury landed homes and are genuine | 99% | median 68 |
| 12 | `area_scope` | string | PG | What the area measures: `floor_reported` the whole unit / `room_reported` the room | 99% | floor 350, room 168 |

> ⚠️ For rooms: rows with `rental_scope=='room'` have a median area of only 11 m², not comparable with whole units; group by `area_scope` when computing rent per square metre.

### 2.3 Location and transport

| # | Field | Type | Source | Description | Coverage | Values |
|---|---|---|---|---|---|---|
| 13 | `district_code` | string | PG | URA planning district (D05 = Clementi / West Coast and so on) | 100% | D05 most (101) |
| 14 | `address` | string | v1 | Address text (house number + street, area); about 18% lack a house number | 100% | — |
| 34 | `postcode` | string | PG detail page | 6-digit postcode (down to the building). Note: a few agents enter placeholder values | 100% | — |
| 35 | `street_name` | string | PG detail page | Standardised street name | 94% | — |
| 36 | `latitude` | float | see #48 | Latitude | **100%** | [1.240, 1.454] |
| 37 | `longitude` | float | see #48 | Longitude | **100%** | [103.693, 103.969] |
| 48 | `coord_source` | string | derived | Coordinate source: `onemap_postcode` (496, OneMap's official geocoding, building level) / `pg_poi_inferred` (21, inferred from walking distances to nearby facilities, error about 165 m) / `onemap_street_geocode` (2, street level) | 100% | — |
| 49 | `coord_error_m` | float | derived | Coordinate uncertainty (metres): inferred ≈ 165; street ≈ 500; not given at postcode level | 4% | — |
| 15 | `mrt_station` | string | PG POI | Nearest MRT station (with its code, such as CR17 Clementi MRT) | 86% | — |
| 16 | `mrt_distance_m` | int | PG POI | Walking distance to the nearest MRT (metres, along the road network) | 86% | median 620 |
| 17 | `mrt_minutes_reported` | int | PG POI | Walking time to the nearest MRT (minutes) | 86% | median 7 |
| 18 | `mrt_operation_status` | string | derived | `operational` / `under_construction` (station name contains U/C) | 84% | operational 423 |

### 2.4 Rental conditions (PG detail page unitDetails; missing = not given on the page)

| # | Field | Type | Description | Coverage | Values |
|---|---|---|---|---|---|
| 21 | `tenant_count_reported` | int | Maximum number of tenants (rooms) | 27% | median 1 |
| 22 | `tenant_gender_label` | string | Tenant gender as labelled by the agent: female / male / any | 27% | any 102 |
| 23 | `gender_restriction` | string | Normalised gender restriction: `no_restriction` / `female_only` / `male_only`. **Use this column for grouping** | 27% | no_restriction 101 |
| 24 | `gender_preference` | string | Gender preference (not given on the page; only 1 row has a value; **better ignored**) | 0% | — |
| 25 | `cooking_policy` | string | Cooking policy: `light_cooking` light cooking / `cooking_any_cooking` any / `cooking_not_allowed` + `not_allowed` not allowed / `cooking_prefer_not_to_say`. Only rooms have values | 18% | light 72 |
| 26 | `furnishing` | string | Furnishing: `fully_furnished` / `partially_furnished` / `unfurnished` / `furnished_unspecified` | 99% | full 258, partial 219 |
| 27 | `landlord_lives_in` | string | Whether the landlord lives in: yes / no (from ownerStays) | 22% | no 71 |
| 28 | `private_bathroom` | string | Private bathroom: filled only when the page states it (yes) | 1% | yes 5 |
| 29 | `air_conditioning` | string | Air-conditioning: yes / no (filled only when a structured field states it) | 40% | yes 208 |
| 30 | `pets_policy` | string | Pets: `no_pets` / `pets_allowed` + `allowed` (filled only when stated) | 19% | no_pets 99 |

> Empty and `unknown` mean the same: **when the page does not give a value, it stays unknown or empty; nothing is inferred**.

### 2.5 Nearby facilities A: OneMap official theme layers (count within 1 km straight-line distance, snapshot 2026-09-18)

| # | Field | Facility | Agency | POIs | Coverage | Median |
|---|---|---|---|---|---|---|
| 38 | `poi_hawker_1km` | Hawker centres | NEA | 129 | 95% | 1 |
| 39 | `poi_library_1km` | Libraries | NLB | 28 | 95% | 0 |
| 40 | `poi_sport_1km` | Sports facilities | SportSG | 45 | 95% | 0 |
| 41 | `poi_healthcare_1km` | Hospitals + registered pharmacies | MOH / HSA | 31+249 | 95% | 2 |
| 42 | `poi_community_1km` | Community clubs | PA | 125 | 95% | 1 |

### 2.6 Nearby facilities B: PropertyGuru "What's nearby" (walking distance along the road network, snapshot 2026-09-17)

| # | Field | Description | Coverage | Median |
|---|---|---|---|---|
| 43 | `pg_school_count` | Number of nearby schools PG lists (including private and international schools) | 97% | 20 |
| 44 | `pg_school_nearest_walk_m` | Walking distance to the nearest school (metres) | 97% | 600 |
| 45 | `pg_school_nearest_walk_min` | Walking time to the nearest school (minutes, at about 80 m/min) | 97% | 7 |
| 46 | `pg_mrt_count` | Number of nearby MRT stations PG lists | 85% | 2 |
| 47 | `pg_mrt_nearest_walk_m` | Walking distance to the nearest MRT (metres) | 85% | 600 |

### 2.7 Nearby facilities C: OpenStreetMap (count within 1 km straight-line distance, snapshot 2026-09-18, ODbL)

| # | Field | Description | POIs | Coverage | Range |
|---|---|---|---|---|---|
| 50 | `poi_fnb_1km` | Food and drink places within 1 km (restaurant / cafe / fast_food / food_court / pub / bar and so on) | 10,724 (island-wide) | 100% | median 64, [3, 1395] |

### 2.8 Time and housekeeping fields

| # | Field | Type | Description |
|---|---|---|---|
| 19 | `listed_date` | date | Listing date (PG lastPosted) |
| 20 | `collected_at` | datetime | v1 collection time (2026-09-09) |
| 32 | `scrape_status` | string | All `active` in this file (listings taken down are in removed_listings.csv) |
| 33 | `enriched_at` | datetime | Reserved, currently empty (the fill-in batch date is in the git history: 2026-09-17) |

---

## 3. Data quality and usage notes

1. **unknown / empty values**: always mean "not given on the page"; nothing was inferred to fill them. Missing values concentrate in the agents' condition fields (present only for rooms: tenant / gender / cooking) and in categories PropertyGuru itself does not carry (gender_preference and private_bathroom are practically unusable).
2. **rental_scope is declared**: ticked by the posting agent; 5 rows were checked and corrected by hand (git `7754c79`). Small entire_unit listings within 1 km are mostly co-living micro studios (Coliwoo, lyf and others), not errors.
3. **Abnormal areas were cleaned**: 6 rooms with an area < 2 m² or > 40 m² (the whole unit's area entered by mistake) were dropped (git `6fb3a8e`).
4. **Three levels of coordinate precision**: for strict distance calculations, use only `coord_source=='onemap_postcode'` (496 rows); for the 21 `pg_poi_inferred` rows, allow ±200 m of uncertainty (method: triangulation from nearby facilities; median error 165 m in a blind test on 485 listings).
5. **The two sets of POI features measure differently**: `poi_*` (OneMap / OSM) are counts within a 1 km straight line; `pg_*` are PropertyGuru walking distances along the road network (more realistic, but only for schools and MRT). Normalise before combining them into a score.
6. **Prices at two dates**: the difference between `rent_monthly_sgd` (9-9) and `rent_monthly_sgd_now` (9-17) gives the price cut over a week; the rent of removed listings is the asking price before removal, so do not mix them with active listings in one regression.
7. **External data**: OneMap (SLA official open data); OpenStreetMap under the ODbL licence, which requires attribution when published; PropertyGuru data for academic analysis only.

## 4. Scripts for reproduction (propertyguru_data/)

| Script | Purpose |
|---|---|
| `scrape_propertyguru.py` | List pages → detail pages (Playwright) |
| `enrich_listings.py` | Main v1 → v2 field fill-in (with the Cloudflare session) |
| `enrich_geo.py` | Postcode / street name + OneMap geocoding |
| `enrich_poi.py` | OneMap theme-layer counts within 1 km |
| `enrich_nearby.py` | Parse PG "What's nearby" + retry coordinates |
| `infer_location.py` | Infer coordinates by POI triangulation (with accuracy calibration) |
| `raw_pg/*.json` | Raw structured data for each listing (for offline recomputation) |
| `poi_themes/*.json` | Snapshots of the OneMap theme layers and OSM food and drink places |
