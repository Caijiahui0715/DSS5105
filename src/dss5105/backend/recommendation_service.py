from typing import Any

from dss5105.backend.services import find_candidates
from dss5105.commute.service import (
    get_cached_commute,
    get_destination,
)
from dss5105.decision.ranking import (
    calculate_suitability_score,
)


def get_commute_status(
    commute: dict[str, Any] | None,
) -> str:
    """
    Describe whether commute data is available.
    """

    if commute is None:
        return "unavailable"

    if commute.get("duration_min") is None:
        return "unavailable"

    return "available"


def build_recommendation_reasons(
    item: dict[str, Any],
) -> list[str]:
    """
    Build short user-facing reasons explaining
    why a listing may be suitable.
    """

    reasons = []

    rent = item.get("rent_monthly_sgd")

    if rent is not None:
        reasons.append(
            f"Monthly rent is SGD {rent}."
        )

    commute = item.get("commute_minutes")

    if commute is not None:
        reasons.append(
            f"Public-transport commute to "
            f"{item.get('destination_name')} is about "
            f"{round(float(commute), 1)} minutes."
        )

    mrt_distance = item.get("mrt_distance_m")

    if mrt_distance is not None:
        reasons.append(
            f"Nearest reported MRT is about "
            f"{round(float(mrt_distance))} m away."
        )

    furnishing = item.get("furnishing")

    if (
        furnishing is not None
        and furnishing != "unknown"
    ):
        reasons.append(
            f"Furnishing: {furnishing}."
        )

    property_type = item.get("property_type")

    if (
        property_type is not None
        and property_type != "unknown"
    ):
        reasons.append(
            f"Property type: {property_type}."
        )

    return reasons


def recommend_listings(
    *,
    faculty_code: str,
    max_budget: float | None = None,
    rental_scope: str | None = None,
    min_bedrooms: int | None = None,
    preferred_furnishing: str | None = None,
    preferred_property_type: str | None = None,
    limit: int = 10,
    candidate_limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Return ranked rental recommendations for one user profile.

    Pipeline:
    1. Retrieve active candidate listings.
    2. Evaluate hard constraints.
    3. Read cached commute to the user's NUS destination.
    4. Calculate suitability score.
    5. Build recommendation explanations.
    6. Rank and return top N.

    FAIL listings are excluded.

    PASS listings are prioritised over
    NEEDS_CONFIRMATION listings.
    """

    destination = get_destination(
        faculty_code
    )

    if destination is None:
        raise ValueError(
            f"Unknown faculty_code: {faculty_code}"
        )

    candidate_results = find_candidates(
        max_budget=max_budget,
        rental_scope=rental_scope,
        min_bedrooms=min_bedrooms,
        limit=candidate_limit,
    )

    recommendations = []

    for constraint_status in [
        "pass",
        "needs_confirmation",
    ]:

        records = candidate_results.get(
            constraint_status,
            [],
        )

        for record in records:

            listing = record["listing"]

            commute = get_cached_commute(
                listing_id=listing["listing_id"],
                destination_id=destination[
                    "destination_id"
                ],
                travel_mode="transit",
            )

            commute_minutes = None
            commute_distance_m = None

            if commute is not None:

                commute_minutes = commute.get(
                    "duration_min"
                )

                commute_distance_m = commute.get(
                    "distance_m"
                )

            ranking = calculate_suitability_score(
                listing,
                max_budget=max_budget,
                commute_minutes=commute_minutes,
                preferred_furnishing=preferred_furnishing,
                preferred_property_type=preferred_property_type,
            )

            item = {
                "listing_id": listing[
                    "listing_id"
                ],

                "title": listing[
                    "title"
                ],

                "listing_url": listing.get(
                    "listing_url"
                ),

                "address": listing.get(
                    "address"
                ),

                "rent_monthly_sgd": listing.get(
                    "effective_rent_monthly_sgd"
                ),

                "district_code": listing.get(
                    "district_code"
                ),

                "district": listing.get(
                    "district"
                ),

                "rental_scope": listing.get(
                    "rental_scope"
                ),

                "room_type": listing.get(
                    "room_type"
                ),

                "property_type": listing.get(
                    "property_type"
                ),

                "bedrooms": listing.get(
                    "bedrooms"
                ),

                "bathrooms": listing.get(
                    "bathrooms"
                ),

                "furnishing": listing.get(
                    "furnishing"
                ),

                "mrt_station": listing.get(
                    "mrt_station"
                ),

                "mrt_distance_m": listing.get(
                    "mrt_distance_m"
                ),

                "latitude": listing.get(
                    "latitude"
                ),

                "longitude": listing.get(
                    "longitude"
                ),

                "faculty_code": faculty_code,

                "destination_name": destination[
                    "destination_name"
                ],

                "commute_minutes": (
                    commute_minutes
                ),

                "commute_distance_m": (
                    commute_distance_m
                ),

                "commute_status": (
                    get_commute_status(
                        commute
                    )
                ),

                "constraint_status": (
                    constraint_status
                ),

                "constraint_evaluation": (
                    record["evaluation"]
                ),

                "suitability_score": (
                    ranking["score"]
                ),

                "score_components": (
                    ranking["components"]
                ),

                "score_weight_used": (
                    ranking["weight_used"]
                ),

                "review_flags": listing.get(
                    "review_flags"
                ),
            }

            item[
                "recommendation_reasons"
            ] = build_recommendation_reasons(
                item
            )

            recommendations.append(
                item
            )

    status_priority = {
        "pass": 0,
        "needs_confirmation": 1,
    }

    recommendations.sort(
        key=lambda item: (
            status_priority[
                item["constraint_status"]
            ],

            -(
                item["suitability_score"]
                if item["suitability_score"]
                is not None
                else -1
            ),
        )
    )

    return recommendations[:limit]