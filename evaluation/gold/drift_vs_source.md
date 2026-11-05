# Gold drift vs the received file

Received file: `source/DSS5105_47_Gold_Answers.json` (430-row snapshot of 10/23).
New gold: `gold/gold_answers.json` (369-row frozen snapshot of 11/02).

| Case | Turn | Confirmed old → new | Needs confirmation old → new | Old IDs now delisted | Top-3 changed | Note |
|---|---|---|---|---|---|---|
| A01 | 1 | 7 → 4 | 3 → 3 | 1 | yes |  |
| A02 | 1 | 16 → 12 | 40 → 35 | 8 | yes |  |
| A03 | 1 | 2 → 2 | 0 → 0 | 0 | no |  |
| A04 | 1 | 65 → 57 | 0 → 0 | 8 | no |  |
| A05 | 1 | 5 → 4 | 15 → 13 | 3 | yes |  |
| A06 | 1 | 14 → 10 | 3 → 3 | 5 | yes |  |
| A07 | 1 | 1 → 0 | 0 → 0 | 1 | yes |  |
| A08 | 1 | 75 → 62 | 0 → 0 | 15 | yes |  |
| A09 | 1 | 55 → 45 | 4 → 5 | 8 | yes |  |
| A10 | 1 | 55 → 49 | 49 → 42 | 13 | yes |  |
| B01 | 1 | 4 → 3 | 19 → 16 | 3 | yes |  |
| B02 | 1 | 37 → 30 | 29 → 25 | 9 | yes |  |
| B03 | 1 | 42 → 35 | 45 → 38 | 12 | yes |  |
| B04 | 1 | 0 → 0 | 115 → 90 | 27 | no |  |
| B05 | 1 | 1 → 1 | 109 → 96 | 13 | no |  |
| B06 | 1 | 54 → 45 | 10 → 9 | 9 | no |  |
| C01 | 1 | 0 → 0 | 0 → 0 | 0 | no |  |
| C02 | 1 | 0 → 0 | 0 → 0 | 0 | no |  |
| C03 | 1 | 0 → 0 | 0 → 0 | 0 | no |  |
| C04 | 1 | 0 → 0 | 0 → 0 | 0 | no |  |
| C05 | 1 | 0 → 0 | 0 → 0 | 0 | no |  |
| C06 | 1 | 0 → 0 | 0 → 0 | 0 | no | relaxation 12 → None |
| G01 | 1 | 87 → 73 | 0 → 0 | 12 | yes |  |
| G01 | 2 | 102 → 89 | 0 → 0 | 12 | yes |  |
| G02 | 1 | 95 → 81 | 0 → 0 | 12 | no |  |
| G02 | 2 | 95 → 81 | 0 → 0 | 12 | yes |  |
| G03 | 1 | 0 → 33 | 120 → 68 | 14 | yes |  |
| G03 | 2 | 62 → 55 | 59 → 52 | 14 | yes |  |
| G04 | 1 | 22 → 19 | 0 → 0 | 3 | yes |  |
| G04 | 2 | 142 → 125 | 0 → 0 | 17 | no |  |
| G05 | 1 | 105 → 91 | 0 → 0 | 13 | yes |  |
| G05 | 2 | 88 → 19 | 0 → 0 | 13 | yes |  |
