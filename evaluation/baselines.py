"""Baselines the agent (B5) is compared with, as the proposal (section 4) sets out.

B1  platform-style: hard filters a rental site offers, then cheapest first.
B2  transparent weighted scoring: every stated condition as a hard filter, then a fixed weighted score.
B3  an LLM recommending straight from the same listing data, without tools (run_baselines.py).
B4  the old fixed LangGraph workflow (graph.py), run by run_eval.py --system workflow.

B1 and B2 take each turn's gold_profile, as if the user had filled in the filters correctly: they
test search and ranking, not understanding the user. They judge each field with gold.py's rules,
so their filters are as good as the gold answer's; what they lack is the rest:
  - a listing whose data does not state a filtered field is dropped, never shown as "needs
    confirmation" (that is how a site's filters behave);
  - B1 has no filter for cooking, tenant gender, live-in landlord, air-conditioning, lease length,
    commute, nearby food, pets or a private bathroom, so it ignores them;
  - neither suggests relaxing a condition, asks a question, or answers anything but a search.
"""

from __future__ import annotations

import math

import gold as gold_rules

# Filters a rental site such as PropertyGuru offers; anything else in the request is ignored by B1.
PLATFORM_FILTERS = {
    "max_price_sgd", "rental_scope", "room_type", "district_code", "property_types", "min_bedrooms",
    "min_bathrooms", "min_area_sqm", "furnished_required", "furnishing_level", "max_mrt_minutes",
    "max_mrt_distance_m",
}
NOT_FILTERS = {"ranking_priority", "occupant_count"}
TOP_K = 3

_DATA = None


def data():
    global _DATA
    if _DATA is None:
        df, commute = gold_rules.load()
        _DATA = df, commute, df.set_index("listing_id")
    return _DATA


def matches(profile: dict, faculty: str | None, fields: set[str] | None = None) -> list[str]:
    """Listings that pass every condition in `fields` (all conditions when None); unknown fails."""
    df, commute, _ = data()
    used = {k: v for k, v in profile.items() if k not in NOT_FILTERS and (fields is None or k in fields)}
    statuses = gold_rules.evaluate(df, used, faculty, commute) if used else {lid: {} for lid in df["listing_id"]}
    return [lid for lid, status in statuses.items() if all(v == gold_rules.PASS for v in status.values())]


def rent(lid: str) -> float:
    return float(data()[2].loc[lid, "rent"])


def b1(profile: dict, faculty: str | None) -> list[str]:
    """Platform filters, cheapest first (ties by listing ID)."""
    return sorted(matches(profile, faculty, PLATFORM_FILTERS), key=lambda lid: (rent(lid), lid))[:TOP_K]


# B2's factors: smaller is better after the sign; a missing value counts as the worst.
def _factor(name: str, lid: str, faculty: str | None) -> float | None:
    _, commute, idx = data()
    row = idx.loc[lid]
    value = {
        "price": gold_rules.clean(row["rent"]),
        "mrt": gold_rules.clean(row["mrt_minutes_reported"]),
        "commute": commute.get((lid, faculty)) if faculty else None,
        "space": None if gold_rules.clean(row["area_sqm"]) is None else -float(row["area_sqm"]),
        "food_places": None if gold_rules.clean(row["poi_fnb_1km"]) is None else -float(row["poi_fnb_1km"]),
    }[name]
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def b2_weights(profile: dict) -> dict[str, float]:
    """Rent and MRT walk always count once; each priority the user stated counts twice."""
    weights = {"price": 1.0, "mrt": 1.0}
    for name in profile.get("ranking_priority") or []:
        weights[name] = 2.0
    return weights


def b2(profile: dict, faculty: str | None) -> list[str]:
    """Every condition as a hard filter, then the weighted sum of min-max scaled factors."""
    ids = matches(profile, faculty)
    if not ids:
        return []
    weights = b2_weights(profile)
    scaled = {}
    for name in weights:
        values = {lid: _factor(name, lid, faculty) for lid in ids}
        known = [v for v in values.values() if v is not None]
        low, high = (min(known), max(known)) if known else (0.0, 0.0)
        scaled[name] = {lid: 1.0 if v is None else (0.0 if high == low else (v - low) / (high - low)) for lid, v in values.items()}
    score = {lid: sum(weights[n] * scaled[n][lid] for n in weights) / sum(weights.values()) for lid in ids}
    return sorted(ids, key=lambda lid: (score[lid], rent(lid), lid))[:TOP_K]


NAMES = {"price": "rent", "mrt": "MRT walk", "commute": "commute to your faculty", "space": "floor area",
         "food_places": "food places within 1 km"}


def reply(system: str, profile: dict | None, shown: list[str]) -> str:
    """A fixed reply built only from the data, so these baselines state nothing they cannot back."""
    if profile is None:
        return ("This search only works with filters such as budget, location and room type. "
                "It cannot answer questions or take actions; please set your filters.")
    if not shown:
        return "No listings match your filters."
    _, _, idx = data()
    if system == "b1":
        head = "Listings matching your filters, cheapest first:"
    else:
        weights = b2_weights(profile)
        head = "Listings matching all your conditions, ranked by a weighted score (" + ", ".join(
            f"{NAMES[n]} x{w:g}" for n, w in weights.items()) + "):"
    lines = [head]
    for i, lid in enumerate(shown, 1):
        row = idx.loc[lid]
        lines.append(f"{i}. {row['title']} (listing {lid}): SGD {rent(lid):,.0f}/month")
    return "\n".join(lines)
