from decimal import Decimal
from typing import Any


DEFAULT_WEIGHTS = {
    "price": 0.25,
    "commute": 0.35,
    "mrt": 0.15,
    "furnishing": 0.10,
    "property_type": 0.15,
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, Decimal):
        return float(value)

    return float(value)


def score_price(
    rent: Any,
    max_budget: float | None,
) -> float | None:
    rent = _to_float(rent)

    if rent is None or max_budget is None:
        return None

    if max_budget <= 0:
        return None

    if rent > max_budget:
        return 0.0

    ratio = rent / max_budget

    if ratio <= 0.5:
        return 100.0

    score = 150 - (100 * ratio)

    return round(
        max(0.0, min(100.0, score)),
        2,
    )


def score_commute(
    duration_min: Any,
) -> float | None:
    """
    Score public-transport commute time to the user's
    NUS representative destination.

    <= 20 min  -> 100
    >= 70 min  -> 0

    Values between 20 and 70 minutes are scaled linearly.
    """

    duration = _to_float(duration_min)

    if duration is None:
        return None

    if duration <= 20:
        return 100.0

    if duration >= 70:
        return 0.0

    score = 100 - (
        (duration - 20) / 50 * 100
    )

    return round(
        max(0.0, min(100.0, score)),
        2,
    )


def score_mrt(
    mrt_distance_m: Any,
) -> float | None:
    distance = _to_float(mrt_distance_m)

    if distance is None:
        return None

    if distance <= 300:
        return 100.0

    if distance <= 600:
        return 80.0

    if distance <= 1000:
        return 60.0

    if distance <= 1500:
        return 40.0

    return 20.0


def score_furnishing(
    listing_furnishing: str | None,
    preferred_furnishing: str | None,
) -> float | None:
    if preferred_furnishing is None:
        return None

    if (
        listing_furnishing is None
        or listing_furnishing == "unknown"
    ):
        return None

    if listing_furnishing == preferred_furnishing:
        return 100.0

    return 40.0


def score_property_type(
    listing_property_type: str | None,
    preferred_property_type: str | None,
) -> float | None:
    if preferred_property_type is None:
        return None

    if (
        listing_property_type is None
        or listing_property_type == "unknown"
    ):
        return None

    if listing_property_type == preferred_property_type:
        return 100.0

    return 40.0


def calculate_suitability_score(
    listing: dict,
    *,
    max_budget: float | None = None,
    commute_minutes: float | None = None,
    preferred_furnishing: str | None = None,
    preferred_property_type: str | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """
    Calculate suitability score for one listing.

    Missing factors are excluded from the denominator
    instead of automatically receiving zero.
    """

    if weights is None:
        weights = DEFAULT_WEIGHTS

    component_scores = {
        "price": score_price(
            listing.get(
                "effective_rent_monthly_sgd"
            ),
            max_budget,
        ),

        "commute": score_commute(
            commute_minutes
        ),

        "mrt": score_mrt(
            listing.get("mrt_distance_m")
        ),

        "furnishing": score_furnishing(
            listing.get("furnishing"),
            preferred_furnishing,
        ),

        "property_type": score_property_type(
            listing.get("property_type"),
            preferred_property_type,
        ),
    }

    weighted_sum = 0.0
    used_weight = 0.0

    for factor, score in component_scores.items():

        if score is None:
            continue

        weight = weights.get(
            factor,
            0.0,
        )

        weighted_sum += (
            score * weight
        )

        used_weight += weight

    if used_weight == 0:
        final_score = None

    else:
        final_score = round(
            weighted_sum / used_weight,
            2,
        )

    return {
        "listing_id": listing.get(
            "listing_id"
        ),
        "score": final_score,
        "components": component_scores,
        "weight_used": round(
            used_weight,
            2,
        ),
    }