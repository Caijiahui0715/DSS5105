# Evaluation set (59 cases)

The gold answers in this version were recomputed on the final data frozen on 2026-11-02 (369 listings). The files we originally received are kept unchanged in `source/`.

## Contents

| Path | What it holds |
|---|---|
| `CONVENTIONS.md` | Evaluation conventions: how each field is judged pass / unknown / fail, how a request is read, and how listings are ranked and conditions relaxed. Confirmed on 2026-11-05 |
| `cases/cases.json` | The 59 cases: the queries, each turn's `gold_profile`, set-up turns, `expected_behavior`, `must` / `must_not`, and the dev / holdout split |
| `cases/holdout_manifest.json` | The IDs of the 20 holdout cases and their SHA-256, sealed on 2026-11-05 |
| `gold/gold_answers.json` | Gold answers for each turn: confirmed listings (ranked), listings that need confirmation (with the unknown fields), counts of exclusion reasons, the top 3, the category C relaxation result and the category H facts |
| `gold/drift_vs_source.md` | Case-by-case comparison of the new and the original gold answers |
| `human_ranking/v6_final/` | **The final human-ranking questionnaire (15 cases)**: the 11 kept V6 cases plus the replacements for A08, A09, B01 and G04. `DSS5105_V6_human_ranking.pdf` is the full questionnaire (each case's image, the five reviewers' ranks and comments, and the comparison with the gold answer and the agent), with the merged `responses.csv`, `key.csv`, `analysis.md` and `images/`. Built by `analyze_human_ranking.py`. Here the gold answer uses the values shown in the images (listing 500203570 at SGD 1,050 a month, where the frozen data has 1,300), and candidates that the ranking rules cannot separate count as tied; `gold_answers.json` is not affected. The 11 original cases are compared with the agent's order from 11/05. The agent never ranked all candidates of the 4 replacement cases, so they are compared with the order the frozen system gives those candidates (`system_order.csv`, computed without the model by `human_ranking_system_order.py`, which must run before `analyze_human_ranking.py`) |
| `human_ranking/responses/` | The raw answers exported from the two Google Forms (the V6 cases and the 4 replacement cases), unchanged |
| `human_ranking/v6_images/`, `v6_key.csv` | The comparison images of the original V6 cases, and the candidates and agent ranks read from those images |
| `human_ranking/form.csv` | A 17-case ranking sheet rebuilt on the frozen data. It was not sent to reviewers as a whole; the replacement cases took their candidates from it |
| `human_ranking/key.csv` | The key to that sheet: listing IDs, sampling source and gold rank. **Not for reviewers** |
| `human_ranking/v6_replacement/` | The replacement cases for A08, A09, B01 and G04 in the V6 questionnaire: comparison images, form settings (`questions.md`) and key (`key.csv`, not for reviewers). Built by `v6_replacement.py` |
| `build_cases.py` | Source files → `cases.json`, including the holdout split |
| `gold.py` | Frozen data + commute cache → gold answers. Uses only pandas and imports no system code |
| `human_ranking.py` | Gold answers → the human-ranking sheet |
| `source/` | The files we received: 47 cases, 8 added A–C cases (xlsx), the original human-ranking sheet and the agent run from 11/05 |
| `check_search.py` | No model: gives each dev turn's `gold_profile` straight to the system's search and ranking and compares the result with the gold answer. Free to run, so search or ranking changes can be retested at once |
| `run_eval.py` | Runs the system (B5, the agent) with the real model and saves one row per turn to `results/<label>.jsonl`, under a header with the code version, the model and the data hashes. Costs money. Runs the dev set unless `--holdout` is given. `--system workflow` runs baseline B4 |
| `score.py` | Computes the metrics from `results/<label>.jsonl` and writes `<label>_review.md`, every turn laid out for reading, and `<label>_behaviour.csv`, the blank behaviour sheet. Uses only the gold answers and the frozen data and imports no system code. Behaviour scores are given by people |
| `baselines.py` | The rules of baselines B1 (portal-style filters + rent order) and B2 (weighted score), and what each of the four baselines is. B1 and B2 take each turn's `gold_profile` directly, without the model |
| `run_baselines.py` | Runs B1, B2 and B3 (an LLM given the listing table, without tools; costs money) in the same format as `run_eval.py`, so `score.py` scores them directly. B4 (the fixed workflow) runs from `run_eval.py --system workflow` |
| `compare_systems.py` | Puts B1–B5 in one table, written to `results/baseline_comparison.md`; the interpretation and caveats are in `results/baseline_report.md` |
| `behaviour_scoring_guide.md` | How behaviour (metric 5) is scored: the steps for raters, how each category is judged, and the cases to agree on before scoring |
| `merge_behaviour.py` | Merges two raters' behaviour sheets, computes agreement and Cohen's κ and lists the disagreements; after discussion, `--final` reports the final behaviour rates |
| `failure_log.md` | The failure cases, in the template of section 6 of the evaluation plan, used for Evaluation.pdf. The dev cases come first (with how they were fixed); the last section is the holdout (recorded only, not fixed) |
| `ranking_summary.md` | Summary of the ranking evaluation: the automatic order checks (dev and holdout), the human-ranking questionnaire (metric 7), and how the different kinds of order disagreement are classified |
| `boundary/` | Boundary tests: off-topic questions, general renting questions, legal and pass questions, prompt injection and over-refusal. Not part of the 59 cases and does not touch `cases.json`; it uses only dev cases, never the holdout. See its `README.md` |

## Results (`results/`)

| File | What it holds |
|---|---|
| `holdout.jsonl`, `holdout_review.md` | The holdout run of the frozen agent (B5): 20 cases, three runs each, and every turn laid out for reading |
| `holdout_report.md` | The holdout report: automatic metrics, behaviour scores and an analysis of each failure |
| `holdout_behaviour.csv` | The blank behaviour sheet written by `score.py` |
| `holdout_behaviour_adjudication.csv`, `holdout_behaviour_final.csv`, `Holdout_Behavioural_Evaluation_Final.md` | Behaviour scoring of the first run: both raters' scores, how each disagreement was settled, and the final scores |
| `b1-*` … `b4-*` | Baselines B1–B4 on the dev set and the holdout (run record, review and blank behaviour sheet) |
| `baseline_comparison.md`, `baseline_report.md` | B1–B5 side by side, and the interpretation |
| `dev1` … `dev5` | Runs of the agent on the dev set while the system was being developed; each header records the code version. `dev4-vague` and `dev5-check` rerun a few cases |

## How to run

From the repository root:

```bash
.venv/Scripts/python.exe evaluation/build_cases.py
```

```bash
.venv/Scripts/python.exe evaluation/gold.py
```

```bash
.venv/Scripts/python.exe evaluation/human_ranking.py
```

`build_cases.py` only needs to run again when the cases change; after changing `CONVENTIONS.md`, run the other two again. All three scripts are deterministic: running them again gives the same output (apart from the generation time in `gold_answers.json`).

The system runs and scoring:

```bash
.venv/Scripts/python.exe evaluation/run_eval.py holdout --holdout --runs 3
```

```bash
.venv/Scripts/python.exe evaluation/score.py holdout
```

```bash
.venv/Scripts/python.exe evaluation/compare_systems.py
```

The holdout was run once, after the system was frozen at commit `1b6ba07`, three runs per case. Its header records commit `38c529e` with uncommitted changes whose code hash (`34c83c86…`) is that of `1b6ba07`, which committed those changes. The holdout cases were never run on the agent before that, and no fix was made after it.

## What changed from the version we received

1. **The data is the frozen version.** The original files used the 430-listing data of 10/23, in which 50 listings had been taken down before 11/02. After recomputing, the number of matches changed in almost every case (see `gold/drift_vs_source.md`), and two conclusions changed:
   - **A07** (D22, 3+ bedrooms, whole unit, up to 4,500): the only match, 500299663, was taken down, so there are now 0 matches. The case stays in category A: it now tests whether the request is understood correctly when nothing matches, and that no listing is offered anyway. It is in the dev set, so it does not affect the holdout results.
   - **C06** (the same conditions plus a 6-month lease): the original conclusion, "signing for 12 months solves it", no longer holds. The gold answer is now "changing the lease alone does not help".
2. **Categories A–C and D–H use one set of rules.** Before, G03 turn 1 ("can cook + has air-conditioning") was judged to have 0 matches, which contradicted A02. Everything now follows `CONVENTIONS.md`, and G03 turn 1 has 33 matches.
3. **Category G now states each turn's `gold_profile`.** The original files only listed the listings, not the conditions. G01, G02 and G05 gained a faculty (Faculty of Science).
4. **Categories E and F gained a set-up turn**, so that "this property" refers to 500074659.
5. **The numbers in category C's `must` are filled in from the gold answer automatically**, so they stay correct if the data changes.
6. **Category H facts are read from the frozen data.** Note H02 and H04: by the latest recorded rent both listings are 900, a tie; by the original advertised price they are 1000 and 900.
7. **12 cases were added** (2026-11-05): A11–A14, B07, B08, C07 and C08 come from `source/DSS5105_Additional_ABC_8_Queries.xlsx` (its Chinese columns are corrupted, so only the English queries and faculty settings were used); G06–G09 were written for the frozen data. So that each case can test what its category is meant to test on the frozen data, the original wording was changed in 4 places, recorded in each case's `changes_from_source`:
   - A11: budget 4,200 → 5,000 (no listing matched the original; the cheapest is 4,300);
   - A13 and C07: "private bathroom" removed (only 3 of the 369 listings state one);
   - B08: the half-sentence "flexible-looking" removed (by the conventions, Flexible allows any lease length).
8. **The holdout is a fixed list** (2026-11-05): only cases never run on the agent, 20 in all: the 12 new cases plus D01, D04, E01, E02, F02, F05, H01 and H02. A04, A05, A06, A10, B04, B06, C03 and C06, which had been run on the agent, and G01–G05, all run on 11/05, moved to the dev set. G01–G05 have dev results only.
9. **The human-ranking sheet was rebuilt**, see the next section.

## The human-ranking sheet

17 cases with 81 candidates in all, every one from the frozen data. Compared with the original sheet:

- Each case shows the fields it is ranked by (commute time to the faculty, number of food places within 1 km, whether the MRT station is open), and states which faculty the commute is to.
- Category G shows both turns of the conversation.
- B04 (0 matches, so ranking means nothing) and C03 and C04 (no strict matches) were left out.
- Near-identical listings (same name, price, area and room type) are not put in the same case.
- When fewer than 5 listings match (A01 and A05 have 4, B01 has 3), the case has fewer than 5 candidates rather than being filled with non-matching ones.

`key.csv` has a column "Order fully set by user". For cases marked yes, the user has said exactly how to rank (for example "cheapest first"), so the human ranking mostly checks the rules; it is better to report them apart from the other cases.
