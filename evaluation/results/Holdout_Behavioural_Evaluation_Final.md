# Holdout Behavioural Evaluation: Final Results

## 1. Evaluation Objective

This evaluation assesses whether the DSS5105 rental recommendation agent performs the requested task correctly and whether its explanations remain grounded in the available listing and tool data. Decision and Explanation are evaluated as separate outcomes.

## 2. Evaluation Dataset

The evaluation covers **25 scored turns from Holdout Run 1**. Each turn is keyed by Case ID and Turn and uses the first recorded Agent response in `evaluation/results/holdout_review.md`. The listing and Gold facts correspond to the frozen evaluation snapshot documented in the project materials.

## 3. Decision and Explanation Scoring Rubric

The Group 3 Evaluation Plan (Metric 5, pp. 4–5) defines Decision as whether the Agent took the correct action, including asking when clarification is needed and returning appropriate recommendations. Explanation assesses whether the stated reasons are consistent with tool results. Both scores are binary and independent.

For this evaluation:

- **Decision Score (0/1)** assesses correct task execution, hard-constraint compliance, appropriate clarification, and required actions.
- **Explanation Score (0/1)** assesses factual grounding, accurate communication of uncertainty, and sufficient explanation of the results.
- Accurately separating confirmed and unverified listings and reporting their counts may satisfy a request to distinguish those categories. Omission of supplementary unknown listings does not automatically constitute a hard-constraint violation, but may reduce explanation completeness.
- A mistake on one dimension does not automatically lower the other dimension.

## 4. Scoring and Adjudication Procedure

Member C and Codex scores were aligned by Case ID and Turn. The 22 cases with matching scores on both dimensions were carried forward. The three discussed cases received the final adjudications supplied for this report: B07=1/1, B08=1/1, and G06 Turn 2=1/0. The final row-level decisions and evidence references are recorded in `holdout_behaviour_final.csv`; the adjudication table retains both original ratings and marks all 25 rows `ADJUDICATED`.

The Codex contribution was AI-assisted and is not described as a second human rating. No Agent rerun or external model call was used for adjudication.

## 5. Final Results

| Metric | Result |
|---|---:|
| Decision Accuracy | **21/25 (84%)** |
| Explanation Accuracy | **20/25 (80%)** |
| Both Correct Rate | **19/25 (76%)** |

Both Correct Rate counts turns where Decision and Explanation are each 1. The target value was not used to modify any score.

## 6. Results by Expected Behaviour

| Expected Behaviour | Turns | Decision Correct | Explanation Correct | Both Correct |
|---|---:|---:|---:|---:|
| answer | 18 | 15/18 (83.3%) | 13/18 (72.2%) | 13/18 (72.2%) |
| clarify | 2 | 1/2 (50.0%) | 2/2 (100%) | 1/2 (50.0%) |
| say_unknown | 2 | 2/2 (100%) | 2/2 (100%) | 2/2 (100%) |
| decline | 2 | 2/2 (100%) | 2/2 (100%) | 2/2 (100%) |
| compare | 1 | 1/1 (100%) | 1/1 (100%) | 1/1 (100%) |

## 7. Disagreement Resolution

- **B07 (1/1):** The Agent reported 71 confirmed fully furnished listings and separately acknowledged two listings with unspecified furnishing. It did not treat those unknown listings as confirmed. The adjudication accepted the category distinction and counts without requiring every pending listing ID.
- **B08 (1/1):** The Agent distinguished 24 confirmed six-month lease options from 37 listings needing confirmation and excluded 28 listings with minimum terms longer than six months. The adjudication accepted accurate category counts as sufficient for this task.
- **G06 Turn 2 (1/0):** The Agent retained the SGD 1,400 cap, applied the air-conditioning and no-live-in-landlord requirements, and presented confirmed listings in ascending rent order. It omitted 34 otherwise eligible listings with unknown condition values, reducing explanation completeness without making the confirmed-only action incorrect.

## 8. Key Failure Cases

- **A12:** The Agent added an unrequested male-preference condition and consequently reported no strict matches despite listings with no gender restriction.
- **A14:** The recommendation order was appropriate, but a 22-minute public-transport commute was described as a walk.
- **C07:** The Agent added `common_room` as a hard filter when the user requested a room generally, then stated that the original criteria were unchanged.
- **D01:** The Agent recommended listings before obtaining the budget and acceptable commute/location boundary.
- **H01:** The Agent said the original advertised rent was unavailable, although the frozen snapshot records S$1,000 original and S$900 latest rent.

These cases illustrate that correct recommendations and grounded explanations can diverge and should remain separately scored.

## 9. Limitations

This is a 25-turn, single-run holdout evaluation against one frozen listing snapshot. It does not establish current listing availability or performance on other user populations. The evaluation includes one human-provided rating file and one AI-assisted rating file; it is not a two-human reliability study, and no human-human inter-rater statistic is claimed. Three disagreements were resolved using the final adjudications supplied for this report. Results should therefore be interpreted as a project-specific behavioural assessment rather than a general performance guarantee.
