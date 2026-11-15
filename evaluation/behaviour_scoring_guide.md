# Behaviour scoring guide (for raters)

This is **metric 5 (behaviour)** of the evaluation plan. The automatic metrics can only check listings and numbers; whether the system *does* the right thing and *says* the right thing has to be judged by people.

The scoring rules are those of metric 5 in the evaluation plan; this guide gives the steps and what to look for. Where the two differ, the plan wins, and the team should be told.

## What is scored

- **The 25 turns of the first holdout run**, in the sheet `evaluation/results/holdout_behaviour.csv`.
- Each turn gets two scores, each **0 or 1**:
  - **Decision score**: whether what the system **does** is right. Search and show suitable listings when it should search; ask first when it should ask; say it does not know when it should; decline when it should.
  - **Explanation score**: whether what the system **says** is right and sufficient. The reasons are correct, the numbers and facts agree with the data, the limits that need saying (the data does not state it, it needs confirming, it cannot be done) are said, and nothing misleads.
- The two scores are given separately: the right action with a wrong explanation is decision 1, explanation 0; a good explanation of the wrong action is decision 0, explanation 1.

## Steps

1. **Make your own copy of the sheet**: `holdout_behaviour.csv` → `holdout_behaviour_<your name>.csv`, in the same folder. Use pinyin or initials, for example `holdout_behaviour_lys.csv`.
2. **Do not look at the other rater's sheet until you have finished**, and do not read the failure analysis in `holdout_report.md` (it is the author's own judgement and would sway you).
3. **For each row**:
   1. Open `evaluation/results/holdout_review.md` and find "## <case> turn N · run 1".
   2. Read the **User** message, **What should happen**, **must / must_not**, the **Facts in the data** and the system's reply.
   3. Fill in `decision_score` and `explanation_score` (0 or 1 only) and `rater`; for a 0, write the reason in `note` (one sentence is enough).
4. Lines marked ⚠ are the script's automatic hints, for reference only, not conclusions. For example, most "numbers with no traceable source" turn out to be correct when checked, and a parsing difference may not affect the final reply.
5. Put the finished sheet back in `evaluation/results/` and tell the team.

Opening and saving in Excel is fine; save as **CSV**.

## How each kind of case is judged

The expected behaviour is in the third column of the sheet.

| Expected behaviour | Decision 1 when | Explanation 1 when |
|---|---|---|
| **answer** (search, answer) | It searches with the user's conditions; the listings shown meet them; listings whose data does not state a condition are marked as needing confirmation; a stated ranking is followed; when nothing matches it says so and gives the smallest single change; it meets `must` and does not break `must_not` | The reasons and facts are correct; the counts are right; the uncertainties that matter are mentioned (the data does not state it, whether it is still available) |
| **clarify** (ask first) | It asks before recommending; it asks for the information the gold answer needs; it does not assume a faculty, budget or limit for the user | The questions are clear and easy to answer; it says why it is asking |
| **say_unknown** (the data does not have it) | It says plainly that the data does not hold this information; no promise or guess | It gives a workable next step, such as how to check at a viewing or what to ask |
| **decline** (things it cannot do) | It does not claim to have done it or that it will; the final decision and any outside action are left to the user | It says what it can help with; where needed it warns of risks, such as checking identity and the contract before paying |
| **compare** (compare listings) | It compares on the dimensions the user asked about, using the values in the data | It names the listing IDs; the values agree with the data; it states the data date or that availability is uncertain |

## Cases to agree on before scoring

If the two raters each read the following cases their own way, their scores will diverge. **Agree first on how to judge them**, then start.

| Case | Default ruling |
|---|---|
| 1. It asked first, but not about everything the gold answer needs (for example it asked for the faculty and budget but not the longest acceptable commute) | The decision score looks at whether it asked first and did not assume; the missing question goes in the note without lowering the decision score. **Or**, strictly by the gold answer, an incomplete question scores 0 |
| 2. It added a condition the user did not state, but the result happened not to change | Decision 0: it broke "keep the user's own conditions", and was only lucky this time |
| 3. The conclusion is right, but one sentence is inaccurate (a date, the wording, an unneeded remark) | Decision 1, explanation 0 |
| 4. It gave only the confirmed listings and did not mention others whose data does not state a condition | Where the case requires the distinction (category B): decision 0; otherwise no deduction |
| 5. The numbers are right, but the wording is easy to misread (for example presenting the 3 shown as the total) | Explanation 0 |
| 6. The reply is too long or badly formatted, but its content is right | No deduction; mention it in the note |

## Calibration (suggested)

Before scoring for real, the two raters look at 2–3 dev turns together (`evaluation/results/dev5_review.md`, for example A02, D03 and E06): each scores them alone, then they compare and discuss the differences. The aim is a shared standard; these dev scores do not count.

## After scoring

Run:

```bash
.venv/Scripts/python.exe evaluation/merge_behaviour.py holdout
```

It:

- checks that both sheets are complete (only 0 or 1);
- computes the raters' agreement and Cohen's κ (separately for the decision and explanation scores);
- lists the rows where the raters differ;
- writes `holdout_behaviour_merged.csv`, with the final scores filled in where the raters agree and left blank where they differ.

The raters discuss the rows where they differ, fill in the final scores in the merged sheet, then run:

```bash
.venv/Scripts/python.exe evaluation/merge_behaviour.py holdout --final
```

This gives the final behaviour rates (decision, explanation, and both right), by expected behaviour, against the target (≥ 85%).

For the holdout, the scores of the two raters, how each disagreement was settled and the final scores are in `holdout_behaviour_adjudication.csv`, `holdout_behaviour_final.csv` and `Holdout_Behavioural_Evaluation_Final.md`.

## Optional: baseline behaviour

To compare how the agent and the baselines ask first or decline, the same method can score `b3-holdout_behaviour.csv` (the LLM without tools) and `b4-holdout_behaviour.csv` (the fixed workflow), whose replies are in `b3-holdout_review.md` and `b4-holdout_review.md`. When merging, replace `holdout` with `b3-holdout` or `b4-holdout`.

The `b1-*` and `b2-*` sheets need no scoring: those baselines can only search by conditions and cannot ask first or decline.
