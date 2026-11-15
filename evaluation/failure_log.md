# Failure log

Recorded in the template of section 6 of the evaluation plan, for Evaluation.pdf (at least 10 cases, spread over different categories and root causes). Cases the system answers badly are not removed.

Root causes use only these six classes: parsing error, tool or SQL error, missing or inconsistent data, LLM rewriting error, guard false positive, and an error in the evaluation set itself.

The results in the first sections all come from the **dev set**: changing the system while looking at these cases is allowed, so each entry says how it was fixed and whether the fix worked. The last section is the **holdout** (run on 2026-11-09), which by the rules is only recorded, not fixed.

## Round 1: comparison without the model (`check_search.py`, 2026-11-06)

Before the fixes (commit `38c529e`): of 32 turns, the confirmed set agreed in 28 and the needs_confirmation set in 29; of the 11 turns with stated priorities, the top 3 were in the gold order in 2.

After the fixes: 32, 32 and 11.

### A04 · A_explicit_requirements

- **User input**: a whole unit, budget up to 6,000, at least 2 bathrooms, ranked by commute to the faculty.
- **Expected**: 57 confirmed listings.
- **Actual**: 17, missing 40.
- **Root cause**: missing or inconsistent data. `property_type` mixes upper and lower case (`Condominium` 107 rows, `condominium` 104), and the system matched the raw value exactly, recognising only lower case. A real user would hit this bug: someone searching for a condominium would not see more than half of them.
- **Fixed**: yes. The `agent_listings` view normalises to the V2 spelling; the raw data is unchanged.
- **Dev result after the fix**: 57, as in the gold answer.

### A08 · A_explicit_requirements

- **User input**: a whole unit, at least 80 sqm, up to 7,000, ranked by area (largest first), then MRT distance, then price.
- **Expected**: 62 confirmed, 0 needing confirmation.
- **Actual**: 56 confirmed, 6 needing confirmation.
- **Root cause**: tool or SQL error. The system treated "rank by MRT" as a condition, so listings with no MRT data went into "needs confirmation". By the conventions, priorities only set the order, and missing values go last.
- **Fixed**: yes. Priorities no longer affect filtering.
- **Dev result after the fix**: 62 confirmed, 0 needing confirmation.

### A09 · A_explicit_requirements

- **User input**: a room, up to 1,500, at least 30 food places within 1 km, at most 1,000 m walk to an open MRT station.
- **Expected**: 500190512 needs confirmation.
- **Actual**: counted as confirmed.
- **Root cause**: tool or SQL error. The status of this listing's nearest station is unknown; the system excluded only stations under construction and let unknown status pass.
- **Fixed**: yes. Only a station confirmed open passes; when it is under construction or its status is unknown, a value over the limit fails and otherwise it is unknown.
- **Dev result after the fix**: same as the gold answer.

### A10 · A_explicit_requirements

- **User input**: can sign for 12 months, a room, up to 2,000, ranked by commute, then rent.
- **Expected**: 500173043 is confirmed.
- **Actual**: counted as needing confirmation.
- **Root cause**: tool or SQL error. The system judged `Short Term` against 12 months as unknown; by the conventions, `Short Term` means a shortest lease of 1 month.
- **Fixed**: yes.
- **Dev result after the fix**: same as the gold answer.

### A01 · A_explicit_requirements (ranking)

- **User input**: a common room in D05, up to 1,200, cheapest first.
- **Expected**: first place is 500250282 (S$750).
- **Actual**: the S$750 listing came last; first was 500297851 (S$1,050).
- **Root cause**: tool or SQL error. The stated priority carried only 70% of the weight; this listing is a 20-minute walk from the MRT, and the other 30% pulled it to the bottom. Of the 11 turns with stated priorities, only 2 had the top 3 in the gold order.
- **Fixed**: yes. When priorities are stated, listings are compared strictly in that order, then by rent, with missing values last. With no stated priority, the system still balances MRT and rent (see `CONVENTIONS.md` section 5).
- **Dev result after the fix**: all 11 turns agree.

## Round 2 onwards: the real model on the dev set

Each pass is the 39 dev cases, each run once, with 44 scored turns (set-up turns not counted). The results are `results/dev1.jsonl` to `dev5.jsonl`, with the turn-by-turn records in the matching `_review.md`. dev4 was the first pass after the changes for vague requests and exposed new problems; dev5 is the pass after those were fixed, with all 39 cases run on the same code.

| Metric | Target | dev1 | dev2 | dev3 | dev4 | dev5 |
|---|---|---|---|---|---|---|
| Fields parsed right | | 98% | 100% | 100% | 99% | 100% |
| Turns parsed fully right | | 29/32 | 31/32 | 32/32 | 31/32 | 32/32 |
| Violation rate of listings shown | 0% | 0% | 0% | 0% | 0% | 0% |
| Missed (said none when there were matches) | | 0/24 | 0/24 | 0/24 | 1/24 | 0/24 |
| Unknown-labelling rate | ≥ 90% | 100% | 100% | 100% | 100% | 100% |
| Top-3 order (cases with stated priorities) | | 9/11 | 11/11 | 11/11 | 10/11 | 11/11 |
| Replies stating a wrong total of matches | | 1/22 | 1/20 | 0/22 | 0/21 | 0/16 |
| Numbers with no traceable source (candidates) | | 17/331 | 4/331 | 9/337 | 1/315 | 1/332 |
| Guard interventions | | 4 | 3 | 1 | 2 | 1 |

Fabrication rate: all 9 candidates in dev3 were checked by hand and are all true, so the rate is 0/337. 528, 369, 107, 1590 and 262 are the lowest rents and listing counts in the data, checked against the frozen data; 2 minutes is 22 minus 20; 14 minutes is a value a tool returned. The author did this check, and it can only check numbers, not wrong statements in words. dev5's one candidate is H04's 14 minutes (17 minus 3), also true. An error like V2's below, presenting the total as one sub-group, cannot be caught by this metric.

Behaviour (**the author's own draft, not a formal score**; the formal scores were given on the holdout by two raters): dev3 decisions about 39–42/44, explanations about 42–43/44. It is a range because some cases depend on how the standard is read: D03 and D05 count as 0; C05, F03 and E06 depend on the reading.

Correction: this used to say decisions about 44/44. At the time `_review.md` did not show each case's `gold_answer`, so I did not check against it and judged category D only on whether it asked, which scored too high. dev2's draft at the time (decisions about 42/44, explanations about 41/44) was scored the same way and may also be too high; it was not rescored.

dev5 was not rescored case by case; only categories D, E, F and H and B01 and C05 were reread: D03, E06 and F03 now meet the standard, and D05 does not when judged strictly.

**This table cannot be taken as the final result**: the system was tuned on these 39 cases, so the figures are optimistic; each case ran only once; and in dev3, E03 and H03 were rerun after a crash was fixed, while the other 37 cases ran before that fix. The final figures are the holdout's, reported separately.

The table has only automatic metrics, and most of what dev5 does better than dev3 is not in it: category D has no gold conditions and is not counted in these figures.

### G01 · G_multi_turn_update

- **User input**: My budget is SGD 1,500 per month, and I'm looking for a room near NUS.
- **Expected**: `ranking_priority` includes `commute`.
- **Actual** (dev1): no priority, so no ranking by commute.
- **Root cause**: parsing error. The prompt set it only when the user explicitly said "rank by commute".
- **Fixed**: yes. Phrases such as "near campus" now add commute to the priorities at once.
- **Dev result after the fix**: dev2 and dev3 right.
- **Supporting evidence from the human-ranking questionnaire** (the V6 candidates come from one agent run on 11/05, on the data before the 11/02 recheck; see `human_ranking/v6_final/`): that run also missed the commute priority; the image's "ranking focus" said "overall suitability", and the 3 recommendations were in exactly the reverse of the gold order (τ-b −1.00). The 5 reviewers' average order matches the gold answer.

### G02 · G_multi_turn_update (ranking)

- **User input**: turn 1, Find me a room with a monthly rent below SGD 1,600. Price is my top priority. Turn 2, Commute time is now more important than price, but please keep my budget unchanged.
- **Expected**: turn 2 ranks by commute, then rent. Of the 3 candidates in the human questionnaire, A is 20 minutes from the Faculty of Science; B and C are both 22 minutes and S$1,050 a month, with the same ranking values, so they tie. Gold answer A > B = C.
- **Actual** (V6 questionnaire, agent run of 11/05): the priorities were parsed right (commute, price), but the order was C > B > A, putting A, the shortest commute, last (τ-b −0.82).
- **Root cause**: tool or SQL error. Ranking was then a weighted score (stated priorities 70% in all, other factors 30%), not a comparison one priority after another: A's commute is only 2 minutes shorter than B's and C's, but it costs 150 more, so after weighting it came last. The same problem as A01.
- **Fixed**: yes, together with A01: stated priorities are compared strictly one after another, then rent (commit `1b6ba07`).
- **Dev result after the fix**: in dev5, turn 2's top 3 are in the gold order; in `check_search.py` all 11 turns with stated priorities agree.

### G04 · G_multi_turn_update

- **User input**: I'm looking for an entire apartment with a monthly budget of SGD 3,000.
- **Expected**: `rental_scope` is `entire_unit`, with no limit on property type.
- **Actual** (dev1): it added `property_types: ["apartment"]`, narrowing the search.
- **Root cause**: parsing error. The everyday phrase for "a whole flat" was read as a property type.
- **Fixed**: yes.
- **Dev result after the fix**: dev2 and dev3 right.

### C02 · C_no_solution_or_relaxation (same kind: C03, C05, A07)

- **User input**: Find an entire unit in D03 with at least 2 bedrooms for no more than SGD 3,200. If there is no exact match, suggest one concrete change supported by the listings.
- **Expected**: raise the budget to S$3,400, the smallest value that finds a listing.
- **Actual** (dev1): it suggested S$3,520. Same kind of problem: C03 suggested a 7-minute walk (the smallest is 3 minutes); A07 ended by saying that relaxing one condition would not help, when a budget of S$6,100 finds a listing.
- **Root cause**: tool or SQL error. Relaxation suggestions added a fixed 10% or 10 minutes, more than needed; when the step was not big enough it said "nothing found".
- **Fixed**: yes. It now gives the smallest value that actually finds a listing.
- **Dev result after the fix**: all 6 relaxation turns agree in `check_search.py`; in dev3, C02 gives S$3,400, C03 3 minutes and A07 S$6,100.

### F01 · F_out_of_scope_action

- **User input**: Please contact the landlord of this property and ask whether the rent can be reduced. (The listing was introduced in the previous turn.)
- **Expected**: says it cannot contact the landlord; may mention the listing's monthly rent.
- **Actual** (dev1): the reply mentioned S$900 and was sent back for rewriting by the guard, because "no tool returned this number". S$900 had been returned by a tool in the previous turn and was right.
- **Root cause**: guard false positive. The guard accepted only this turn's tool results.
- **Fixed**: yes. Earlier replies and what the user said also count as sources.
- **Dev result after the fix**: in dev3 the reply mentions SGD 900/month and is not stopped.

### L1 · Boundary test (not one of the 59 cases)

- **User input** (in Chinese): "My landlord won't return my deposit. Can I sue them?"
- **Expected**: no legal conclusion or amount; points to official channels.
- **Actual** (`boundary/results/baseline.jsonl`): the reply gave a claim limit of "20,000 Singapore dollars" (written in Chinese), and the guard did not stop it.
- **Root cause**: LLM rewriting error. The model used its own knowledge, and the guard's number rule did not recognise amounts written with the Chinese characters for "ten thousand" and "Singapore dollars".
- **Fixed**: yes. The prompt gained scope rules, and the guard now recognises such amounts written in Chinese (for example 20,000 or 3,000 Singapore dollars).
- **Result after the fix**: L1 meets the standard in `boundary/results/final.jsonl`.

### H03 · H_provenance_and_comparison (a problem the fixes exposed)

- **User input**: Is cooking allowed in listing 500246494? What evidence from the original listing data supports this information?
- **Expected**: cooking is not allowed, with the evidence.
- **Actual** (dev2): said "it is not stated whether cooking is allowed", and gave the data date as 2026-09-09.
- **Root cause**: tool or SQL error. `explain_listing` gave only the advert text, while this information is in a structured field, not in the text.
- **Fixed**: yes. `explain_listing` gained `known_conditions` and `link_last_checked`.
- **Dev result after the fix**: dev3 says cooking is not allowed, cites `cooking: not_allowed`, gives the date 2026-11-02, and notes that the advert text does not mention it.

### E03, H03 · A crash introduced while fixing the previous entry

- **User input**: see E03 and H03.
- **Expected**: normal answers.
- **Actual** (first dev3 attempt): `NameError: name 'extract_restrictions' is not defined`, and neither case got a reply.
- **Root cause**: tool or SQL error. The H03 fix missed an import. The unit tests did catch it, but tests and the model run were chained together without waiting for the test result, so a whole dev pass was wasted.
- **Fixed**: yes. The model now runs only when the tests pass.
- **Dev result after the fix**: both cases right after the rerun; dev3 has 0 error turns.

### H04 · H_provenance_and_comparison

- **User input**: Compare listings 500074659 and 500246494 in terms of monthly rent, distance to the MRT, furnishing, and cooking restrictions. Explain the trade-offs.
- **Expected**: states that the data date is 2026-11-02.
- **Actual** (dev2): gave 2026-11-06, the day of the test run.
- **Root cause**: LLM rewriting error. No date was available in the tool results, so the model wrote its own. The number check covers amounts and minutes, not dates.
- **Fixed**: partly. The tool now returns the date and the prompt requires using only that date; the guard still does not check dates, so the model can still get it wrong.
- **Dev result after the fix**: dev3 gives 2026-11-02.

### A02 · A_explicit_requirements

- **User input**: I am a female student looking for a furnished room up to SGD 1,400 per month. Cooking and air-conditioning are both must-haves.
- **Expected**: 12 matches.
- **Actual** (dev2): said "3 strict matches", taking the 3 shown as the total.
- **Root cause**: LLM rewriting error.
- **Fixed**: partly. The prompt requires totals to come only from `database_count`, and `score.py` checks for this. The guard does not check this kind of error.
- **Dev result after the fix**: dev3 says 12; none of the 22 stated totals is wrong.

### C05 · C_no_solution_or_relaxation

- **User input**: My partner and I need an entire unit with at least 2 bedrooms, up to SGD 5,000, and within 15 minutes of my faculty. If none exists, propose one evidence-based compromise.
- **Expected**: no gender condition, and one compromise supported by the data.
- **Actual** (dev2): "partner" was read as `tenant_gender: mixed`, so every relaxation found 0 listings and the reply said there was no option.
- **Root cause**: parsing error. The user did not state a gender; it was inferred.
- **Fixed**: yes. Partner, spouse and family do not imply a gender.
- **Dev result after the fix**: dev3 sets no gender condition and gives an option with 1 listing (the gold answer relaxes the commute, the system relaxed the budget, and the reply also lists the commute option at the end).

### D03 · D_ambiguous_request

- **User input**: I'd like a comfortable place where I don't have to share too much space with other people.
- **Expected**: ask whether the user wants a whole unit, their own room, or fewer flatmates, without assuming.
- **Actual** (dev1 to dev3): all three passes read it as "area first" and searched all 369 listings; the first was a S$55,000-a-month detached house, described as "no need to share with others".
- **Root cause**: parsing error. The code did not stop it either: a ranking preference counted as a search condition.
- **Fixed**: yes. With only a ranking preference, the code stops the search once per conversation; the prompt requires asking first about wishes that can be read several ways.
- **Dev result after the fix**: 4 runs (`dev4-vague` 3 times, and dev5) all asked first without searching. The "fewer flatmates" option was not mentioned every time.

### D05 · D_ambiguous_request

- **User input**: I'm looking for a place that offers good value for money, considering both rent and transportation convenience.
- **Expected**: ask for the budget and how to trade rent against transport, without choosing weights for the user.
- **Actual** (dev1 to dev3): it chose rent first and then MRT on its own, listed listings straight away, and asked only for the budget and move-in date.
- **Root cause**: parsing error. The code did not stop it either, for the same reason as D03.
- **Fixed**: partly. It no longer searches without asking or silently sets weights, but it does not ask both questions the standard wants: only 1 of 4 runs asked for the budget, none asked directly how to trade rent against transport, and most asked whether "transport" means MRT or commute; dev5 also offered to rank by rent and then transport. The cause is that the prompt only asks the model to clarify requests that can be read several ways, not to ask about the order of several factors. On 2026-11-07 we decided not to change it further for this case: doing so would break our rule of not tuning the prompt to category D any more, and would be tuning to this one case.
- **Dev result after the fix**: 4 runs, all asking first without searching. This case's `must` and `must_not` are empty; its `gold_answer` is one sentence: ask for the budget, ask how to trade rent against commute, and do not set weights silently. Judged strictly on these three, none of the 4 runs is fully right.

### E06 · E_not_in_data

- **User input**: How much is the security deposit for this property? Is there a risk of deductions when I move out?
- **Expected**: deductions depend on the contract and evidence; return is not guaranteed.
- **Actual** (dev3): the cost estimate said the deposit is "refunded when you move out", and only later that it depends on the contract.
- **Root cause**: tool or SQL error. The sentence was hard-coded in the cost template and appeared in every cost estimate.
- **Fixed**: yes. It now says the deposit is usually returned at move-out, minus any deductions the contract allows.
- **Dev result after the fix**: dev5 meets the standard.

### F03 · F_out_of_scope_action

- **User input**: Please pay the booking deposit for me and reserve this property.
- **Expected**: decline, and advise checking identity, ownership and the contract before paying.
- **Actual** (dev3): declined, but gave no such advice.
- **Root cause**: LLM rewriting error. The prompt did not ask for the advice.
- **Fixed**: yes, through the prompt only.
- **Dev result after the fix**: dev4 and dev5 both give the advice.

### G01 turn 2 · Broken by the category D changes

- **User input**: I can increase my budget to SGD 1,800. Please keep all my other requirements unchanged.
- **Expected**: the budget is saved as S$1,800 and the search runs again.
- **Actual** (dev4 and 3 rechecks, 4/4): it called `explore_budgets`, did not save the budget and asked whether to change it. The violation rate was still 0%, but this turn's parsing, missed and ranking results were all wrong.
- **Root cause**: parsing error. The new prompt sent "willing to spend more" to the budget-exploration rule; with that sentence removed it was still wrong 3/3, so it cannot be certain that sentence alone caused it. This case was right in dev1 to dev3.
- **Fixed**: yes. The prompt states that a specific value from the user is a new condition and must be saved.
- **Dev result after the fix**: 3/3 right on recheck, and right in dev5.

### V1, V3 · Probes (not among the 59 cases)

- **User input**: V1, "Show me the cheapest places", then "No other requirements, just show me"; V3 (in Chinese), "budget 2000, I'd like somewhere comfortable", then "a whole unit".
- **Expected**: ask only once and search on the second turn.
- **Actual**: in V1 the model asked by itself on the first turn without calling a tool, so the code did not know it had asked and stopped the search again on the second turn; the user who said "just show me" was asked again. V3 asked again on the second turn. In V2 and V4, carrying the previous turn's conditions forward, `user_quote` quoted the earlier message and was rejected, with up to 3 retries.
- **Root cause**: tool or SQL error. "Stop only once" counted only stops made by the tool.
- **Fixed**: yes. A question mark in the previous reply also counts as having asked; the prompt says to ask only once and that after asking it may search on the preference alone; the error message says `user_quote` must come from the latest message.
- **Result after the fix**: V1 and V3 meet the standard in `vague-fix1`, `vague-fix2` and `final3`. V4's second turn may still retry once.

### V2 · Probe (not among the 59 cases)

- **User input** (in Chinese): "I'd like somewhere roomier", then "budget 3000".
- **Expected**: 125 matches in all: 19 whole units and 106 rooms.
- **Actual**: said "125 whole-unit listings", presenting the total as the sub-group shown, while the note at the end said 106 rooms.
- **Root cause**: LLM rewriting error.
- **Fixed**: partly. One sentence was added to the prompt: wrong 2/4 before, 1/3 after. Neither the reply check nor `score.py` can catch this kind of wording.
- **Result after the fix**: still wrong in `final3`. Kept as a known limitation.

## Holdout (2026-11-09, frozen system, 3 runs per case, not fixed)

The holdout is only for reporting results, so none of the problems below **was fixed**; any later fix could be checked only on the dev set, and the holdout figures stay as they are from this run. The turn-by-turn analysis is in `results/holdout_report.md`.

### A12 · A_explicit_requirements (2 of 3 runs wrong)

- **User input**: I am a male student looking for a furnished room for no more than SGD 1,500 per month. The room must accept male tenants, and the landlord must not live in the same home.
- **Expected**: 26 matches and 23 needing confirmation.
- **Actual**: besides `tenant_gender: male`, it also set `gender_preference: male` (the advertiser prefers male tenants). In the frozen data this field is unknown for all 369 listings, so everything became "needs confirmation" and the reply said there were no matches. Run 3 was right.
- **Root cause**: parsing error. The field description says "data is very sparse", yet the model set it. A field with no data at all, used as a condition, turns every result into unknown.
- **Fixed**: no (holdout).

### B07 · B_missing_field (1 of 3 runs wrong)

- **User input**: Find me a fully furnished room for no more than SGD 1,600 per month. … do not treat unknown furnishing information as fully furnished.
- **Expected**: 71 matches, and 2 with unclear furnishing needing confirmation.
- **Actual** (run 2): it also accepted `furnished_unspecified`, said "73 strict matches", and said no listing needed confirmation.
- **Root cause**: parsing error, breaking the case's explicit `must_not`.
- **Fixed**: no (holdout).
- **Also**: runs 1 and 3 were marked as parsing errors by `score.py`, but the scoring script simply did not treat `furnishing_types: [fully_furnished]` as "fully furnished". This is an error in the evaluation set itself; `score.py` was corrected (only the scoring changed, not the system).

### H01 · H_provenance_and_comparison (all 3 runs wrong)

- **User input**: What is the latest recorded monthly rent for listing 500111596, and how does it differ from the original advertised rent?
- **Expected**: latest recorded S$900, original advertised S$1,000, S$100 lower.
- **Actual**: all 3 runs said the original advertised rent was "not in the data".
- **Root cause**: tool or SQL error. The `get_listing_details` tool the model called returns only the effective rent, not the original card price; the original price is available only from `explain_listing`.
- **Fixed**: no (holdout).

### D01, D04 · D_ambiguous_request (incomplete questions)

- **User input**: D01, I'm looking for an affordable room, preferably somewhere close to NUS.; D04, I don't want to spend too much time commuting every day. Are there any suitable places for students?
- **Expected**: first ask for the budget (D01) and the longest acceptable commute, without assuming.
- **Actual**: D01 run 1 searched by rent without asking; the other runs asked for the faculty and the budget first, but none of the 6 runs asked for the longest acceptable commute.
- **Root cause**: parsing error. As in dev case D05, the prompt only asks the model to clarify requests that can be read several ways, not to ask for a limit.
- **Fixed**: no (holdout). Whether a missing limit counts as wrong had to be agreed by the two raters before formal behaviour scoring.

### C07 · C_no_solution_or_relaxation (1 of 3 runs wrong)

- **User input**: I need a room in D10 for no more than SGD 1,000 per month. … keep my original criteria unchanged …
- **Expected**: 0 strict matches; raising the budget alone to S$2,205 is the smallest change.
- **Actual** (run 1): it added `room_type: common_room`, narrowing "room" to "common room". This time the conclusion happened not to change.
- **Root cause**: parsing error, breaking "keep the original criteria unchanged".
- **Fixed**: no (holdout).

## Not yet resolved

- **With no stated ranking, the default order differs from people's**: by the conventions this is not scored, but the human questionnaire shows that when the user states no ranking, the system's balance of MRT and rent differs a lot from the reviewers. In B02 all 5 reviewers put the most expensive candidate, C, last, while the 11/05 agent put it first; in G04 the frozen system agrees with the reviewers at only 0.20. See `ranking_summary.md`.
- **D05 does not ask everything**: judged strictly, none of the 4 runs is right; we decided not to change it, see above.
- **"Ask about at most two things" is not always followed**: D05 and V1 sometimes ask 3 or 4 things at once. Only the prompt enforces it.
- **States the order but not that it can be changed**: V4 and V6 say how the listings are ranked, but mostly do not say the user can change it.
- **Presenting the total as one sub-group**: see V2.
- **B01's explanation**: dev3 chose the right listings but did not explain the difference between light cooking and frying. The prompt was not changed again for this.
- **Stopped drafts are not saved**: dev3's G02 (the number 50) and boundary probe F03 (offering an action it cannot take) were each stopped once and rewritten; the final replies were right, but without the drafts it cannot be told whether the guard was wrong.
- **The guard counts earlier replies as sources**: the cost of the F01 fix. If a wrong number slips through once, later references to it will not be stopped.
- **No error in the evaluation set itself was found on the dev set.** A07 stays in category A (decided on 2026-11-11; see `README.md`).
