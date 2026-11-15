# b1-holdout

Version: {"system": "B1_platform_filter", "split": "holdout", "commit": "4df9bb2", "baseline_code_sha256": "49bd28c000c5a72d912cd839f845807585fe3bb73273d6ef9c26afa78883022c", "model": null, "listings_sha256": "f8fc729545ad80be55f1c8628cf0663d10035b997e28c181e96c0bb2d477241b", "commute_sha256": "515dd93c38b4200af27061d3eb85686cb0d8c9c774d6ab8a0d0f268a39e3d229", "cases_sha256": "42191b90979ca0a3b59afcd27ff51baf5f76636e35e69bb7b0acd9be74eb49d7", "started_at": "2026-11-11T10:06:31+00:00"}

## A11 turn 1 · run 1 · expected answer

**User**: Find me an entire unit in D21 with at least 2 bedrooms and a monthly rent of no more than SGD 5,000. Rank all eligible listings by lower rent first.


**Tools**: []; **Shown**: ['500103088', '500265707', '500281128']

**must**: ['Return only entire units in D21 with at least 2 bedrooms at or below SGD 5,000', 'Rank the confirmed listings by rent, lowest first']  
**must_not**: ['Return room rentals or listings outside D21', 'Treat a listing with an unknown bedroom count as confirmed']


**Facts in the data** (frozen data, latest rent):
- 500103088: S$4300 (negotiable); unknown; condominium; 70.98 sqm; DT5 Beauty World MRT, 10 min walk, 800.0 m; furnishing partially_furnished; cooking unknown; air-con unknown; gender unknown; landlord lives in unknown; pets unknown
- 500265707: S$4800 (unknown); unknown; Condominium; 70.98 sqm; CR16 Maju MRT, 7 min walk, 620 m; furnishing partially_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown
- 500281128: S$4800 (unknown); unknown; Condominium; 70.98 sqm; CR16 Maju MRT, 7 min walk, 620 m; furnishing partially_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. Daintree Residence (listing 500103088): SGD 4,300/month
2. Pinetree Hill (listing 500265707): SGD 4,800/month
3. Pinetree Hill (listing 500281128): SGD 4,800/month
```

## A12 turn 1 · run 1 · expected answer

**User**: I am a male student looking for a furnished room for no more than SGD 1,500 per month. The room must accept male tenants, and the landlord must not live in the same home.


**Tools**: []; **Shown**: ['25420249', '500250282', '25558520']

**must**: ['Exclude female-only rooms and rooms whose landlord lives in', 'Treat male-only and no-restriction rooms as gender-compatible', 'Mark rooms with an unstated gender rule, furnishing or landlord arrangement as needing confirmation']  
**must_not**: ['Treat an unstated gender rule as confirmed', 'Treat an unstated landlord arrangement as not living in']

- ⚠ Parsing differs: gold {"tenant_gender": "male", "landlord_not_living_in": true}, system {"tenant_gender": null, "landlord_not_living_in": null}; extra {}
- ⚠ Listing with unknown fields presented as a match: 25420249
- ⚠ Listing with unknown fields presented as a match: 500250282
- ⚠ Listing that fails a condition was shown: 25558520

**Facts in the data** (frozen data, latest rent):
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 25558520: S$800 (asking); common_room; hdb_flat; 11.15 sqm; NS3A Brickland MRT, 12 min walk, 1010.0 m; furnishing fully_furnished; cooking light_cooking; air-con unknown; gender female_only; landlord lives in yes; pets no_pets

```text
Listings matching your filters, cheapest first:
1. The Tanamera (listing 25420249): SGD 750/month
2. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
3. 329 Bukit Batok Street 33 (listing 25558520): SGD 800/month
```

## A13 turn 1 · run 1 · expected answer

**User**: Find me a room for no more than SGD 2,200 per month with air-conditioning. It must be within a 10-minute walk of an operating MRT station. Rank the eligible rooms by shorter MRT walk first, then lower rent.


**Tools**: []; **Shown**: ['500029855', '25420249', '500107898']

**must**: ['Require air-conditioning and a walk of 10 minutes or less to an operating station', 'Rank by MRT walk, then rent']  
**must_not**: ['Count a station under construction or of unknown status as operating']

- ⚠ Parsing differs: gold {"air_conditioning_required": true}, system {"air_conditioning_required": null}; extra {}
- ⚠ Listing with unknown fields presented as a match: 25420249
- ⚠ Listing with unknown fields presented as a match: 500107898
- ⚠ Order differs: system ['500029855', '25420249', '500107898'], gold ['500098200', '500040015', '60059436']

**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500107898: S$800 (asking); common_room; hdb_flat; 13.94 sqm; NS3 Bukit Gombak MRT, 10 min walk, 810.0 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 323 Bukit Batok Street 33 (listing 500107898): SGD 800/month
```

## A14 turn 1 · run 1 · expected answer

**User**: I need a room for no more than SGD 1,800 per month and can sign a 12-month lease. My public-transport commute to my faculty must not exceed 40 minutes. Rank suitable rooms by shorter faculty commute first, then lower rent.


**Tools**: []; **Shown**: ['500029855', '25420249', '500250282']

**must**: ['Use School of Computing commute data', "Treat a listing's stated term as its minimum accepted lease", 'Rank by faculty commute, then rent']  
**must_not**: ['Use MRT walking time as the faculty commute', 'Assume an unstated lease accepts 12 months']

- ⚠ Parsing differs: gold {"lease_months": 12, "max_commute_minutes": 40}, system {"lease_months": null, "max_commute_minutes": null}; extra {}
- ⚠ Listing that fails a condition was shown: 500029855
- ⚠ Listing that fails a condition was shown: 25420249
- ⚠ Listing with unknown fields presented as a match: 500250282
- ⚠ Order differs: system ['500029855', '25420249', '500250282'], gold ['500298034', '500211799', '500263166']

**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; 54 min to School of Computing; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; 70 min to School of Computing; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; 25 min to School of Computing; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
```

## B07 turn 1 · run 1 · expected answer

**User**: Find me a fully furnished room for no more than SGD 1,600 per month. Separate listings that explicitly confirm they are fully furnished from otherwise eligible listings whose furnishing level is not stated. Exclude listings explicitly described as partially furnished or unfurnished, and do not treat unknown furnishing information as fully furnished.


**Tools**: []; **Shown**: ['25420249', '500250282', '25558520']

**must**: ['List explicitly fully furnished rooms as confirmed', 'List rooms whose furnishing level is not stated as needing confirmation', 'Exclude partially furnished and unfurnished rooms']  
**must_not**: ['Treat unknown or unspecified furnishing as fully furnished']

- ⚠ Parsing differs: gold {"furnishing_level": "full"}, system {"furnishing_level": "full"}; extra {}

**Facts in the data** (frozen data, latest rent):
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 25558520: S$800 (asking); common_room; hdb_flat; 11.15 sqm; NS3A Brickland MRT, 12 min walk, 1010.0 m; furnishing fully_furnished; cooking light_cooking; air-con unknown; gender female_only; landlord lives in yes; pets no_pets

```text
Listings matching your filters, cheapest first:
1. The Tanamera (listing 25420249): SGD 750/month
2. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
3. 329 Bukit Batok Street 33 (listing 25558520): SGD 800/month
```

## B08 turn 1 · run 1 · expected answer

**User**: I need a room for no more than SGD 1,800 per month and I can sign only a 6-month lease. Separate listings that explicitly accept a 6-month lease from otherwise eligible listings whose lease term is not stated. Exclude listings that explicitly require more than 6 months, and do not treat an unknown lease term as confirmed acceptance of a 6-month lease.


**Tools**: []; **Shown**: ['500029855', '25420249', '500250282']

**must**: ['Treat Flexible and Short Term leases as accepting 6 months', 'Mark rooms with an unstated lease term as needing confirmation', 'Exclude rooms whose stated minimum lease is 1 or 2 years']  
**must_not**: ['Treat an unstated lease term as accepting 6 months']

- ⚠ Parsing differs: gold {"lease_months": 6}, system {"lease_months": null}; extra {}
- ⚠ Listing with unknown fields presented as a match: 500250282

**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
```

## C07 turn 1 · run 1 · expected answer

**User**: I need a room in D10 for no more than SGD 1,000 per month. If there is no strict match, keep my original criteria unchanged and identify the smallest evidence-based adjustment that produces at least one candidate. Change only one requirement at a time.


**Tools**: []; **Shown**: []

**must**: ['State that the strict set is empty', 'Offer a budget of SGD 2,205 as the smallest single change', 'Keep room scope and D10 fixed in that option']  
**must_not**: ['Return over-budget rooms as strict matches', 'Change two requirements at once']


```text
No listings match your filters.
```

## C08 turn 1 · run 1 · expected answer

**User**: Find me an entire unit with at least 2 bedrooms for no more than SGD 4,000 and a public-transport commute of no more than 15 minutes to my faculty. If no exact match exists, do not silently relax the criteria. Test one condition at a time and recommend the smallest supported change, such as a higher budget or a longer commute limit.


**Tools**: []; **Shown**: ['500188102', '500053744', '500020165']

**must**: ['State that the strict set is empty', 'Report the single changes tested: a 29-minute commute limit; no; changing max_price_sgd alone does not produce a confirmed match', 'Use Faculty of Science commute data']  
**must_not**: ['Silently relax the criteria', 'Change budget and commute together']

- ⚠ Parsing differs: gold {"max_commute_minutes": 15}, system {"max_commute_minutes": null}; extra {}
- ⚠ Listing that fails a condition was shown: 500188102
- ⚠ Listing that fails a condition was shown: 500053744
- ⚠ Listing that fails a condition was shown: 500020165

**Facts in the data** (frozen data, latest rent):
- 500188102: S$3000 (asking); unknown; hdb_flat; 64.01 sqm; NS19 Toa Payoh MRT, 18 min walk, 1393 m; 50 min to Faculty of Science; furnishing unfurnished; cooking unknown; air-con unknown; gender unknown; landlord lives in unknown; pets unknown
- 500053744: S$3200 (unknown); unknown; HDB Flat; 83.98 sqm; NS13 Yishun MRT, 14 min walk, 1130 m; 69 min to Faculty of Science; furnishing fully_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown
- 500020165: S$3399 (negotiable); unknown; hdb_flat; 103.03 sqm; BP2 South View LRT, 9 min walk, 740.0 m; 57 min to Faculty of Science; furnishing fully_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 20 Lorong 7 Toa Payoh (listing 500188102): SGD 3,000/month
2. 329 Yishun Ring Road (listing 500053744): SGD 3,200/month
3. 401 Choa Chu Kang Avenue 3 (listing 500020165): SGD 3,399/month
```

## D01 turn 1 · run 1 · expected clarify

**User**: I'm looking for an affordable room, preferably somewhere close to NUS.

**What should happen**: Ask for a maximum monthly budget and an acceptable commute/location boundary before recommending listings.

**Tools**: []; **Shown**: []

**must**: []  
**must_not**: []


```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```

## D04 turn 1 · run 1 · expected clarify

**User**: I don't want to spend too much time commuting every day. Are there any suitable places for students?

**What should happen**: Ask for the commute destination and maximum acceptable travel time; do not invent a faculty or time limit.

**Tools**: []; **Shown**: []

**must**: []  
**must_not**: []


```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```

## E01 turn 1 · run 1 · expected say_unknown

**Said earlier**: ['Tell me about listing 500074659.']

**User**: Is the landlord of this property easy to get along with?

**What should happen**: Say that landlord personality is not verified in the dataset. Do not claim a landlord is friendly; suggest a viewing/call and concrete questions.

**Tools**: []; **Shown**: []

**must**: []  
**must_not**: []


**Facts in the data** (frozen data, latest rent):
- 500074659: S$900 (negotiable); common_room; hdb_flat; 18.58 sqm; BP11 Segar LRT, 3 min walk, 210.0 m; furnishing partially_furnished; cooking light_cooking; air-con yes; gender female_only; landlord lives in yes; pets no_pets

```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```

## E02 turn 1 · run 1 · expected say_unknown

**Said earlier**: ['Tell me about listing 500074659.']

**User**: Does this property have good sound insulation? Is it noisy at night?

**What should happen**: Say that sound insulation and night noise are not reliably recorded. Do not promise quietness; suggest viewing at relevant hours and checking construction/traffic.

**Tools**: []; **Shown**: []

**must**: []  
**must_not**: []


**Facts in the data** (frozen data, latest rent):
- 500074659: S$900 (negotiable); common_room; hdb_flat; 18.58 sqm; BP11 Segar LRT, 3 min walk, 210.0 m; furnishing partially_furnished; cooking light_cooking; air-con yes; gender female_only; landlord lives in yes; pets no_pets

```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```

## F02 turn 1 · run 1 · expected decline

**Said earlier**: ['Tell me about listing 500074659.']

**User**: Please arrange a property viewing for tomorrow at 3 PM.

**What should happen**: State that the system cannot book a viewing. It may provide the listing link and a viewing-request template, but must not claim a booking.

**Tools**: []; **Shown**: []

**must**: []  
**must_not**: []


**Facts in the data** (frozen data, latest rent):
- 500074659: S$900 (negotiable); common_room; hdb_flat; 18.58 sqm; BP11 Segar LRT, 3 min walk, 210.0 m; furnishing partially_furnished; cooking light_cooking; air-con yes; gender female_only; landlord lives in yes; pets no_pets

```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```

## F05 turn 1 · run 1 · expected decline

**Said earlier**: ['Tell me about listing 500074659.']

**User**: This property looks like a good choice, right? Just make the final decision for me and proceed with renting it.

**What should happen**: Provide decision support and trade-offs, but leave the final decision and any external action to the user; do not claim to proceed.

**Tools**: []; **Shown**: []

**must**: []  
**must_not**: []


**Facts in the data** (frozen data, latest rent):
- 500074659: S$900 (negotiable); common_room; hdb_flat; 18.58 sqm; BP11 Segar LRT, 3 min walk, 210.0 m; furnishing partially_furnished; cooking light_cooking; air-con yes; gender female_only; landlord lives in yes; pets no_pets

```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```

## G06 turn 1 · run 1 · expected answer

**User**: I'm looking for a room for no more than SGD 1,400 a month. Show the cheapest first.


**Tools**: []; **Shown**: ['500029855', '25420249', '500250282']

**must**: ['Add air-conditioning and no live-in landlord in turn 2', 'Keep the SGD 1,400 cap and the rent-first order', 'Mark rooms with unstated air-con or landlord arrangement as needing confirmation', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ['Drop the budget in turn 2']


**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
```

## G06 turn 2 · run 1 · expected answer

**User**: I also need air-conditioning, and the landlord must not live in the same home. Keep my budget.


**Tools**: []; **Shown**: ['500029855', '25420249', '500250282']

**must**: ['Add air-conditioning and no live-in landlord in turn 2', 'Keep the SGD 1,400 cap and the rent-first order', 'Mark rooms with unstated air-con or landlord arrangement as needing confirmation', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ['Drop the budget in turn 2']

- ⚠ Parsing differs: gold {"air_conditioning_required": true, "landlord_not_living_in": true}, system {"air_conditioning_required": null, "landlord_not_living_in": null}; extra {}
- ⚠ Listing with unknown fields presented as a match: 500029855
- ⚠ Listing with unknown fields presented as a match: 25420249
- ⚠ Listing with unknown fields presented as a match: 500250282
- ⚠ Order differs: system ['500029855', '25420249', '500250282'], gold ['500297851', '60151578', '24020232']

**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
```

## G07 turn 1 · run 1 · expected answer

**User**: Find me an entire unit in D05 with at least 2 bedrooms for no more than SGD 5,500.


**Tools**: []; **Shown**: ['23998139', '24626814', '25099392']

**must**: ['Replace D05 with D03 in turn 2', 'Keep entire unit, at least 2 bedrooms and SGD 5,500', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ['Search D05 and D03 together in turn 2']


**Facts in the data** (frozen data, latest rent):
- 23998139: S$4500 (unknown); unknown; HDB Flat; 95.6 sqm; ?, ? min walk, ? m; furnishing fully_furnished; cooking unknown; air-con unknown; gender unknown; landlord lives in unknown; pets unknown
- 24626814: S$4500 (asking); unknown; condominium; 61.04 sqm; CC24 Kent Ridge MRT, 17 min walk, 1353 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender unknown; landlord lives in unknown; pets unknown
- 25099392: S$4500 (unknown); unknown; Condominium; 58.99 sqm; ?, ? min walk, ? m; furnishing partially_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 713 Clementi West Street 2 (listing 23998139): SGD 4,500/month
2. Normanton Park (listing 24626814): SGD 4,500/month
3. The Clement Canopy (listing 25099392): SGD 4,500/month
```

## G07 turn 2 · run 1 · expected answer

**User**: Actually, search in D03 instead of D05. Everything else stays the same.


**Tools**: []; **Shown**: ['500255361', '500299461', '500266966']

**must**: ['Replace D05 with D03 in turn 2', 'Keep entire unit, at least 2 bedrooms and SGD 5,500', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ['Search D05 and D03 together in turn 2']


**Facts in the data** (frozen data, latest rent):
- 500255361: S$3400 (asking); unknown; hdb_flat; 53.98 sqm; TE16 Havelock MRT, 4 min walk, 350.0 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender unknown; landlord lives in unknown; pets unknown
- 500299461: S$3600 (unknown); unknown; HDB Flat; 65.96 sqm; EW19 Queenstown MRT, 7 min walk, 610 m; furnishing partially_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown
- 500266966: S$4600 (unknown); unknown; HDB Flat; 110.93 sqm; EW19 Queenstown MRT, 9 min walk, 740 m; furnishing partially_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 14 Taman Ho Swee (listing 500255361): SGD 3,400/month
2. 162 Mei Ling Street (listing 500299461): SGD 3,600/month
3. 59 Strathmore Avenue (listing 500266966): SGD 4,600/month
```

## G08 turn 1 · run 1 · expected answer

**User**: I need a room for no more than SGD 1,200 a month.


**Tools**: []; **Shown**: ['500029855', '25420249', '500250282']

**must**: ['Raise the cap to SGD 1,600 in turn 2', 'Return to SGD 1,200 in turn 3 and add the cooking requirement', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ['Keep the SGD 1,600 cap in turn 3']


**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
```

## G08 turn 2 · run 1 · expected answer

**User**: Let me raise the budget to SGD 1,600.


**Tools**: []; **Shown**: ['500029855', '25420249', '500250282']

**must**: ['Raise the cap to SGD 1,600 in turn 2', 'Return to SGD 1,200 in turn 3 and add the cooking requirement', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ['Keep the SGD 1,600 cap in turn 3']


**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
```

## G08 turn 3 · run 1 · expected answer

**User**: Sorry, go back to my original budget, but now cooking must be allowed.


**Tools**: []; **Shown**: ['500029855', '25420249', '500250282']

**must**: ['Raise the cap to SGD 1,600 in turn 2', 'Return to SGD 1,200 in turn 3 and add the cooking requirement', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ['Keep the SGD 1,600 cap in turn 3']

- ⚠ Parsing differs: gold {"cooking_required": true}, system {"cooking_required": null}; extra {}
- ⚠ Listing with unknown fields presented as a match: 500029855
- ⚠ Listing with unknown fields presented as a match: 25420249
- ⚠ Listing with unknown fields presented as a match: 500250282

**Facts in the data** (frozen data, latest rent):
- 500029855: S$528 (asking); shared_room; shophouse; 16.72 sqm; EW11 Lavender MRT, 6 min walk, 510.0 m; furnishing unfurnished; cooking unknown; air-con yes; gender female_only; landlord lives in unknown; pets unknown
- 25420249: S$750 (unknown); common_room; Condominium; 9.29 sqm; EW4 Tanah Merah MRT, 5 min walk, 390 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown
- 500250282: S$750 (asking); common_room; hdb_flat; 13.94 sqm; EW23 Clementi MRT, 20 min walk, 1523 m; furnishing fully_furnished; cooking unknown; air-con unknown; gender no_restriction; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. 747 north bridge road (listing 500029855): SGD 528/month
2. The Tanamera (listing 25420249): SGD 750/month
3. 707 Clementi West Street 2 (listing 500250282): SGD 750/month
```

## G09 turn 1 · run 1 · expected answer

**User**: Show me entire units for no more than SGD 4,000, cheapest first.


**Tools**: []; **Shown**: ['24205038', '500299696', '500071694']

**must**: ['Keep the same confirmed set in turn 2', 'Rank by floor area, largest first, in turn 2', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ["Turn 'larger area' into a new filter"]


**Facts in the data** (frozen data, latest rent):
- 24205038: S$1590 (unknown); unknown; Terraced House; 13.94 sqm; CR17 Clementi MRT, 17 min walk, 1430 m; furnishing partially_furnished; cooking unknown; air-con unknown; gender unknown; landlord lives in unknown; pets unknown
- 500299696: S$1650 (unknown); unknown; HDB Flat; 11.15 sqm; EW20 Commonwealth MRT, 6 min walk, 520 m; furnishing partially_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown
- 500071694: S$2400 (asking); studio; apartment; 14.86 sqm; DT21 Bencoolen MRT, 4 min walk, 340.0 m; furnishing fully_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. West Coast Drive (listing 24205038): SGD 1,590/month
2. 90 Commonwealth Drive (listing 500299696): SGD 1,650/month
3. Coliwoo - Midtown ( Near SMU, NAFA, Bugis Area ) (listing 500071694): SGD 2,400/month
```

## G09 turn 2 · run 1 · expected answer

**User**: Now rank them by larger floor area first. The budget stays the same.


**Tools**: []; **Shown**: ['24205038', '500299696', '500071694']

**must**: ['Keep the same confirmed set in turn 2', 'Rank by floor area, largest first, in turn 2', 'Apply the latest turn while keeping every unchanged hard constraint']  
**must_not**: ["Turn 'larger area' into a new filter"]

- ⚠ Order differs: system ['24205038', '500299696', '500071694'], gold ['19954468', '21538676', '500020165']

**Facts in the data** (frozen data, latest rent):
- 24205038: S$1590 (unknown); unknown; Terraced House; 13.94 sqm; CR17 Clementi MRT, 17 min walk, 1430 m; furnishing partially_furnished; cooking unknown; air-con unknown; gender unknown; landlord lives in unknown; pets unknown
- 500299696: S$1650 (unknown); unknown; HDB Flat; 11.15 sqm; EW20 Commonwealth MRT, 6 min walk, 520 m; furnishing partially_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown
- 500071694: S$2400 (asking); studio; apartment; 14.86 sqm; DT21 Bencoolen MRT, 4 min walk, 340.0 m; furnishing fully_furnished; cooking unknown; air-con yes; gender unknown; landlord lives in unknown; pets unknown

```text
Listings matching your filters, cheapest first:
1. West Coast Drive (listing 24205038): SGD 1,590/month
2. 90 Commonwealth Drive (listing 500299696): SGD 1,650/month
3. Coliwoo - Midtown ( Near SMU, NAFA, Bugis Area ) (listing 500071694): SGD 2,400/month
```

## H01 turn 1 · run 1 · expected answer

**User**: What is the latest recorded monthly rent for listing 500111596, and how does it differ from the original advertised rent?

**What should happen**: Answer only from the structured snapshot facts, cite the listing IDs and distinguish snapshot evidence from current availability.

**Tools**: []; **Shown**: []

**must**: ['Cite the listing IDs', 'Quote values that match the snapshot', 'Separate snapshot facts from current availability']  
**must_not**: ['Invent a value that is not in the snapshot']


**Facts in the data** (frozen data, latest rent):
- 500111596: S$900 (starting_from); common_room; condominium; 9.29 sqm; EW26 Lakeside MRT, 8 min walk, 630.0 m; furnishing fully_furnished; cooking light_cooking; air-con unknown; gender no_restriction; landlord lives in no; pets no_pets

```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```

## H02 turn 1 · run 1 · expected compare

**User**: Compare listings 500111596 and 500074659 in terms of monthly rent and distance to the MRT. Which listing has an advantage in each aspect?

**What should happen**: Answer only from the structured snapshot facts, cite the listing IDs and distinguish snapshot evidence from current availability.

**Tools**: []; **Shown**: []

**must**: ['Cite the listing IDs', 'Quote values that match the snapshot', 'Separate snapshot facts from current availability']  
**must_not**: ['Invent a value that is not in the snapshot']


**Facts in the data** (frozen data, latest rent):
- 500111596: S$900 (starting_from); common_room; condominium; 9.29 sqm; EW26 Lakeside MRT, 8 min walk, 630.0 m; furnishing fully_furnished; cooking light_cooking; air-con unknown; gender no_restriction; landlord lives in no; pets no_pets
- 500074659: S$900 (negotiable); common_room; hdb_flat; 18.58 sqm; BP11 Segar LRT, 3 min walk, 210.0 m; furnishing partially_furnished; cooking light_cooking; air-con yes; gender female_only; landlord lives in yes; pets no_pets

```text
This search only works with filters such as budget, location and room type. It cannot answer questions or take actions; please set your filters.
```
