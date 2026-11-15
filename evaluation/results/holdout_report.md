# Holdout test report (2026-11-09)

## 1. Set-up

| Item | Details |
|---|---|
| System | B5, the agent: commit `38c529e` plus uncommitted changes (`uncommitted_py_sha256` = `34c83c86…e736e4`). Those changes were then committed as `1b6ba07` (system code and tests); `evaluation/boundary/run_probes.py` and the evaluation results are in the next commit |
| Model | `gpt-5.6-luna` |
| Cases | The 20 holdout cases (A11–A14, B07, B08, C07, C08, D01, D04, E01, E02, F02, F05, G06–G09, H01, H02), sealed hash `9b8340f7…b61b422a` |
| Runs | 3 runs per case: 60 conversations, 75 scored turns, 0 errors |
| Data | The frozen data `rental_data_v2.csv` (369 listings), hash `f8fc7295…7241b` |
| Records | Raw run `holdout.jsonl`; turn-by-turn record `holdout_review.md`; behaviour sheet `holdout_behaviour.csv` |

**Data check**: the data, commute and case hashes recorded at run time are the same as when the gold answers were generated. The listings the agent's database can search (active) are exactly these 369, with the same rent for every one. All 32 listings shown or compared in the 3 runs are in the frozen data. Regenerating the gold answers with `gold.py` gives exactly the copy used for scoring.

**Unit tests**: 6 of 280 fail, all because their expected values still come from the old data (430 listings). This does not affect these results, but those tests should have been updated before the freeze.

## 2. Automatic metrics

| Metric | Result | Target | Met |
|---|---|---|---|
| Violation rate of listings shown | 0% (every listing shown is a match) | 0% | ✅ |
| Unknown-labelling rate (listings needing confirmation marked as such) | Not estimable (0/0): no listing with unknown fields was shown | ≥ 90% | – |
| Fabrication rate | 0/470 (after checking by hand, see 4.1) | < 2% | ✅ |
| Fields parsed right | 99% | | |
| Turns parsed fully right | 47/51 | | |
| Missed (matches exist but none was shown) | 2/45 | | |
| Top-3 order (cases with stated priorities) | 21/21 | | |
| Replies stating a wrong total of matches | 1/22 | | |
| Turns whose outcome differed across the 3 runs | 4/25 (A12, B07, C07, D01) | | |
| Mean time per turn | 8.6 seconds | | |

An earlier version of this report gave the unknown-labelling rate as 21/21 by mistake; no listing needing confirmation was shown in this run, so the rate cannot be estimated.

By category:

| Category | Turns | Parsed fully | Missed | Order | Untraced | Guard |
|---|---|---|---|---|---|---|
| A | 12 | 10/12 | 2/12 | 9/9 | 0/117 | 0 |
| B | 6 | 5/6 | 0/6 | – | 2/57 | 0 |
| C | 6 | 5/6 | – | – | 0/42 | 0 |
| D | 6 | – | – | – | 1/7 | 0 |
| E | 6 | – | – | – | – | 0 |
| F | 6 | – | – | – | 0/1 | 0 |
| G | 27 | 27/27 | 0/27 | 12/12 | 0/221 | 1 |
| H | 6 | – | – | – | 0/25 | 0 |

**Correction to the scoring script**: in the first scoring, "turns parsed fully right" was 45/51. B07 runs 1 and 3 were marked wrong because of the script; the system had understood them correctly (see 4.2). After seeing the holdout results, I changed one field mapping in `score.py` and scored again, giving 47/51. Only the scoring script changed; the system code did not.

## 3. Behaviour

**Formal scores.** The 25 turns of run 1 were scored by two raters, one team member and an AI-assisted rater (Codex), who agreed on 24/25 decisions and 23/25 explanations before the three disagreements were settled. Final scores: decision 21/25 = 84%, explanation 20/25 = 80%, both right 19/25 = 76% (target ≥ 85%). Details are in `Holdout_Behavioural_Evaluation_Final.md`, `holdout_behaviour_final.csv` and `holdout_behaviour_adjudication.csv`.

**Author's first reading (draft, not the formal score).** Categories D, E, F and H are mainly about behaviour. Below is the author's first judgement of all three runs against each case's `gold_answer`. Category G was judged by the automatic metrics only, without reading each turn's behaviour.

| Case | 3 runs | Notes |
|---|---|---|
| A11, A13, A14, B08, C08, G06–G09 | 3/3 | All automatic metrics right |
| A12 | 1/3 | Failure 1 |
| B07 | 2/3 | Failure 2 |
| C07 | 2/3 | Failure 6: run 1 narrowed "room" to "common room" |
| D01 | 0/3 strict; 2/3 lenient | Failure 4 |
| D04 | 0/3 strict; 3/3 lenient | Failure 5 |
| E01, E02 | 3/3 | Says the data does not hold this information, makes no promise, and gives questions to ask at a viewing |
| F02, F05 | 3/3 | Says it cannot book a viewing or decide for the user; F05 also advises checking identity, ownership and the contract before paying |
| H01 | 0/3 | Failure 3 |
| H02 | 3/3 | Cites both IDs; by the latest records the rents tie (900 vs 900); MRT distances right; states the data date |

Total (60 conversations): 47/60 = 78% strict, 52/60 = 87% lenient.

## 4. Failure analysis

Root causes use the six classes of the evaluation plan: parsing error, tool or SQL error, missing or inconsistent data, LLM rewriting error, guard false positive, and an error in the evaluation set itself.

The holdout is for reporting only: **none of these problems is fixed on the holdout**. Any fix could be checked only on the dev set, and the holdout figures stay as they are from this run.

### Failure 1 · A12 · A_explicit_requirements (2 of 3 runs failed; the most serious)

- **User input**: I am a male student looking for a furnished room for no more than SGD 1,500 per month. The room must accept male tenants, and the landlord must not live in the same home.
- **Expected**: 26 matches and 23 needing confirmation. The listings shown should be matches.
- **Actual**: runs 1 and 2 said "No strict matches", with all 49 needing confirmation, and marked the 3 candidates as needing confirmation. Those 3 (500260916, 500297851, 60110616) are recorded as `no_restriction`, landlord not living in and fully furnished, so they are confirmed matches. Run 3 was right and marked all 3 as matches.
- **Root cause**: parsing error. "Must accept male tenants" maps to `tenant_gender: male`, which the system did set. But runs 1 and 2 also set `gender_preference: male`, meaning "the advertiser prefers male tenants". In the frozen data this field is `unknown` for all 369 listings, so adding the condition turned every listing into "needs confirmation".
- **Why the impact is so large**: this is more than one extra condition. Once a field with no values in the data is treated as a condition, every result becomes "unknown". The reply then honestly says "0 matches", and the user sees "no homes". The field description says "Data is very sparse", and the parsing instructions say to set it only when the user asks for it explicitly, but the model ignored this in 2 of 3 runs.
- **Possible fix** (to be checked on the dev set only): once the user sets `tenant_gender`, do not set `gender_preference`; or, for a field with no data at all, tell the user the data does not hold it instead of using it as a condition.

### Failure 2 · B07 · B_missing_field (1 of 3 runs failed)

- **User input**: Find me a fully furnished room for no more than SGD 1,600 per month. Separate listings that explicitly confirm they are fully furnished from otherwise eligible listings whose furnishing level is not stated. … do not treat unknown furnishing information as fully furnished.
- **Expected**: 71 matches (stated as fully furnished) and 2 needing confirmation (25130091 and 24417854, whose furnishing is `furnished_unspecified`).
- **Actual** (run 2): the accepted furnishing types were set to `fully_furnished` plus `furnished_unspecified`, so it said "73 strict matches" and that no listing had unclear furnishing. The 3 listings shown happened to be fully furnished, so the violation rate did not catch it.
- **Root cause**: parsing error. The user said plainly not to count unclear furnishing as full, yet the model added `furnished_unspecified` to the accepted types. This breaks the case's `must_not`.
- **Runs 1 and 3**: set `furnishing_types: [fully_furnished]`, which is right.

### Failure 3 · H01 · H_provenance_and_comparison (3 of 3 runs failed)

- **User input**: What is the latest recorded monthly rent for listing 500111596, and how does it differ from the original advertised rent?
- **Expected**: latest recorded rent S$900, original advertised rent S$1,000, a drop of S$100.
- **Actual**: all 3 runs gave the latest rent as S$900 (right), but all said "the original advertised rent is not in the data, so they cannot be compared" (wrong).
- **Root cause**: tool or SQL error. In all 3 runs the model called `get_listing_details`. That tool returns only the effective rent (`rent_monthly_sgd`, using the latest value where there is one), not the price on the advert card (`rent_monthly_sgd_card`). The original price is available only from `explain_listing`. The model truthfully reported that the tool did not give it, but said "the data does not have it", which sounds like missing data.
- **Related**: H02 compares the rents of 500111596 and 500074659, and all 3 runs said they tie (900 vs 900). By the conventions this is right (see item 6 of `README.md`), but none mentioned that the original prices are 1,000 vs 900. Same cause.
- **Possible fix**: when the original and latest prices differ, `get_listing_details` returns both. This is the same kind of problem as dev case H03: the information is in the data, but the tool used does not return it.

### Failure 4 · D01 · D_ambiguous_request (run 1 failed; runs 2 and 3 incomplete)

- **User input**: I'm looking for an affordable room, preferably somewhere close to NUS.
- **Expected**: before recommending, ask for the highest monthly budget and the acceptable commute or area.
- **Actual**:
  - Run 1: it searched without asking, chose "cheapest first" on its own, listed the 3 cheapest of all 107 rooms, and only asked for the faculty at the end. It never asked for a budget.
  - Runs 2 and 3: it asked first and did not search. It asked for the faculty and the budget, but not the longest acceptable commute.
- **Root cause**: parsing error. Run 1 read "affordable" as the ranking preference "cheapest first" and also set `rental_scope: room`, then searched straight away. The dev-set rule "with only a ranking preference, ask once first" did not trigger this time, possibly because `rental_scope` is a real condition. This is a guess, not checked in the code. The 3 runs behaved differently, so behaviour on this case is unstable.
- **Note**: 107 is the true number of rooms in the frozen data, not a fabrication.

### Failure 5 · D04 · D_ambiguous_request (3 of 3 runs incomplete)

- **User input**: I don't want to spend too much time commuting every day. Are there any suitable places for students?
- **Expected**: ask for the commute destination and the longest acceptable commute, without assuming a faculty or a time.
- **Actual**: all 3 runs asked first, did not search and did not assume a faculty. They asked for the faculty (the destination) and what "suitable for students" means, but none asked for the longest acceptable commute.
- **Root cause**: parsing error, as in dev case D05: the instructions only ask the model to clarify requests that can be read several ways, not to ask for a limit. "I don't want to commute too long" was read as ranking by commute, not as a condition that needs a number.
- **How to judge**: strictly by `gold_answer` this is 0/3; judging only "asks first, does not assume" it is 3/3. The two raters had to agree on the rule before formal scoring.

### Failure 6 · C07 · C_no_solution_or_relaxation (run 1 failed)

- **User input**: I need a room in D10 for no more than SGD 1,000 per month. If there is no strict match, keep my original criteria unchanged and identify the smallest evidence-based adjustment … Change only one requirement at a time.
- **Expected**: 0 strict matches; raising the budget alone to S$2,205 is the smallest change. Room and D10 stay as they are.
- **Actual** (run 1): it also set `room_type: common_room`, and the reply said "common room in D10". The conclusion (S$2,205, 1 listing) happened to match the gold answer. Runs 2 and 3 were right.
- **Root cause**: parsing error. The user said room (any room); the system narrowed it to a common room. This breaks "keep the original criteria unchanged". It did not change the conclusion this time, but if D10 had only master rooms, the relaxation result would have been wrong.

### Other notes (not failures)

**4.1 Numbers with no traceable source: none of the 3 is fabricated**
- B08 run 1, "28 listings failed the 6-month lease condition": among rooms within budget, 23 have a 1-year lease and 5 a 2-year lease, 28 in all. True.
- D01 run 1, "107 room listings": the frozen data has exactly 107 rooms. True.
- B07 run 2, "73": the wrong total of failure 2 (71 matches + 2 needing confirmation). Not invented, and already counted under "wrong total".
- So the fabrication rate is 0/470. This was checked by the author, and only numbers can be checked this way, not wrong statements in words.

**4.2 False alarm from the scoring script: B07 runs 1 and 3**
- The gold answer uses `furnishing_level: full` for "must be fully furnished"; the system uses `furnishing_types: [fully_furnished]`. Both mean the same thing. The script lacked this mapping and marked a parsing error.
- Root cause: an error in the evaluation set itself (the scoring script). The mapping was added to `score.py` and the run scored again.

**4.3 G07 turn 1 was stopped once by the guard**
- The draft contained a number, 900, that no tool had returned, so it was stopped and rewritten. The rewritten reply was right (12 matches, correct top 3).
- The stopped draft was not saved, so it cannot be told whether the model was wrong or the guard was a false positive. This is the same limitation recorded on the dev set.

**4.4 Three tool-argument errors, all recovered automatically**
- A13 run 1, A11 run 2 and B07 run 3: when saving conditions, the `user_quote` was the model's paraphrase, not the user's words, and the tool rejected it. The model retried and succeeded; every final result was right, only slower.

## 5. Root causes

| Root cause | Cases | Runs |
|---|---|---|
| Parsing error | A12 (sets a field with no data), B07 (counts unclear as fully furnished), C07 (narrows the room type), D01 (searches without asking), D04 (does not ask for a limit) | 2 + 1 + 1 + 3 + 3 |
| Tool or SQL error | H01 (the details tool does not return the original price) | 3 |
| Error in the evaluation set | B07 false alarm in scoring | 2 (corrected) |
| Guard false positive | G07 (cannot be determined) | 1 |
| Missing or inconsistent data | None | – |
| LLM rewriting error | No case of its own (B07's wrong total follows from its parsing error) | – |

## 6. Conclusions

1. **The hard metrics are all met**: 0 violations among the listings shown and no fabricated numbers. When data is only partly present, the system keeps "confirmed" and "needs confirmation" apart.
2. **The main risk is understanding the user**: 5 of the 6 failures are parsing errors, and the same case was handled differently across the 3 runs (A12, B07, C07, D01). A12 has the largest consequence: one extra condition with no data turns "26 matches" into "0 matches".
3. **Vague requests are not fully clarified**: D01 and D04 both asked first and did not search blindly (apart from D01 run 1), but neither asked for a commute limit. This is the same problem as dev case D05, so it is not limited to that one case.
4. **A tool is missing a field**: in H01 the tool does not return the original price; this has nothing to do with the model, and its fix is the clearest.
5. **Limitations**: only 3 runs per case; the formal behaviour scores cover run 1 only; category G was not read turn by turn for behaviour; the holdout raters are a team member and an AI-assisted rater.

## 7. What followed

- Behaviour was scored formally on `holdout_behaviour.csv`, with the D-category rule agreed first (see section 3).
- The cases above were added to `failure_log.md`, marked as holdout and not fixed.
