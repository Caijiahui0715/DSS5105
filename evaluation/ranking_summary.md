# Ranking evaluation summary

Ranking is evaluated in two ways:

1. **Automatic**: where the user states priorities, the system's top 3 must be in the gold order (`CONVENTIONS.md` section 5). The order is not checked where no priority is stated.
2. **Human (metric 7)**: 5 reviewers rank candidate listings, and their ranks are compared with the gold answer and the agent.

## 1. Automatic: cases with stated priorities (13 cases, 18 turns)

| Case | Set | Turns | Priorities | Result |
|---|---|---|---|---|
| A01 | Dev | 1 | Rent | dev5 ✓ |
| A04 | Dev | 1 | Commute → rent | dev5 ✓ |
| A08 | Dev | 1 | Area → MRT → rent | dev5 ✓ |
| A09 | Dev | 1 | Food places → MRT | dev5 ✓ |
| A10 | Dev | 1 | Commute → rent | dev5 ✓ |
| G01 | Dev | 1, 2 | Commute | dev5 ✓ ✓ |
| G02 | Dev | 1, 2 | Rent; commute → rent | dev5 ✓ ✓ |
| G05 | Dev | 1, 2 | Commute | dev5 ✓ ✓ |
| A11 | Holdout | 1 | Rent | 3/3 ✓ |
| A13 | Holdout | 1 | MRT → rent | 3/3 ✓ |
| A14 | Holdout | 1 | Commute → rent | 3/3 ✓ |
| G06 | Holdout | 1, 2 | Rent | 3/3 ✓ |
| G09 | Holdout | 1, 2 | Rent; area → rent | 3/3 ✓ |

Dev set (dev5): 11/11. Holdout: 21/21 over the 3 runs. Before the fix (commit `38c529e`), only 2 of the 11 turns agreed in `check_search.py`, because ranking then used a weighted score instead of comparing priorities one after another (A01 and G02 in `failure_log.md`).

The dev figures come from cases the system was tuned on and are optimistic; the holdout's 21/21 is the final result.

## 2. Human-ranking questionnaire (metric 7)

The full questionnaire, each case's image and every reviewer's ranks are in `human_ranking/v6_final/DSS5105_V6_human_ranking.pdf`; the figures are in `analysis.md` in the same folder.

- 15 cases, all from the dev set; 5 reviewers (team members), filled in from 2026-11-05 to 11-08.
- The candidates of the 11 original cases are the top 3 recommended by one agent run on 11/05. That run used the data before the 11/02 recheck, and the ranking had not yet been fixed.
- A08, A09, B01 and G04 had a listing among their original candidates that was later taken down, so they were replaced with candidates drawn from the gold answer. The agent shows only its top 3 and never ranked all of these candidates, so for these 4 cases the comparison is with how the frozen system ranks the candidates (computed without the model).
- The questionnaire's gold answer uses the values shown in the images (listing 500203570 at SGD 1,050 a month); candidates with exactly the same ranking values count as tied.

| Group | Cases | Between reviewers (W) | Reviewers vs gold | Reviewers vs 11/05 agent | 11/05 agent vs gold |
|---|---|---|---|---|---|
| User stated a ranking | A01, A04, A08, A09, G01, G02, G05 | 0.40 | 0.49 | 0.22 | 0.16 |
| User stated no ranking | A02, A05, B01, B02, B03, B06, G03, G04 | 0.39 | 0.34 | 0.03 | 0.36 |

The figures are mean τ-b (1 complete agreement, −1 completely reversed). The last two columns cover only the 11 original cases.

How the frozen system ranks the candidates of the 4 replacement cases: in A08, A09 and B01, every candidate's rank equals the gold answer (τ-b 1.00), including listings ranked 57th and 59th; in G04, where the user stated no ranking, the system agrees with the gold answer at 0.11 and with the reviewers at 0.20.

## 3. Kinds of disagreement and how each counts

| Disagreement | Example | A system failure? | Where it is recorded |
|---|---|---|---|
| The user stated a ranking and the system did not follow it | G01 (−1.00) and G02 (−0.82), both the 11/05 agent | Yes. Both were fixed on the dev set | G01 and G02 in `failure_log.md` |
| The user stated no ranking and the system's default order differs from people's | B02: all 5 reviewers put the most expensive candidate, C, last, while the 11/05 agent put it first; G04: frozen system vs reviewers 0.20 | No (by the conventions only stated rankings are checked); recorded as a known limitation | "Not yet resolved" in `failure_log.md` |
| Reviewers disagree with the gold answer | A09 at 0.48; cases with no stated ranking 0.34 on average | Not a system problem: it tests the gold answer's rules | Section 2 of this page |

## 4. Conclusions

1. **The frozen system ranks by the rules**: where priorities are stated, every turn agrees on both the dev set and the holdout; among the replacement cases, A08 and A09, which state priorities, also agree candidate by candidate.
2. **The gold rules hold up when the user is explicit**: reviewers agree with the gold answer more where a ranking is stated (0.49) than where it is not (0.34). In A01, A04 and A08, single-turn cases with explicit requirements, all 5 reviewers' first choice is the gold answer's first.
3. **With no stated ranking there is no single right order**: reviewers weigh furnishing, flatmates, MRT and bathrooms, and "lowest rent" is not a consensus. This supports checking the order only where a ranking is stated; but the system's default order (balancing MRT and rent) does not necessarily match people's judgement either, which is a direction for improvement.
4. **Reviewers agree very little on multi-turn cases** (W of only 0.04 to 0.16 for G01, G02 and G05). G01's image states the ranking focus as "overall suitability", so reviewers may not have known to rank by commute.

## 5. Limitations

- Only 5 reviewers, all team members; 3 to 5 candidates per case; the human ranking covers only the dev set.
- The 11 original cases are compared with the 11/05 agent (old data, before the fix), which is not the frozen system's result. For the frozen system's ranking, see section 1.
- The images of the 4 replacement cases are in English; the rest are in Chinese.
