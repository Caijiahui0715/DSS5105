from dss5105.backend.services import (
    get_candidate_pool,
)
from dss5105.commute.service import (
    get_cached_commute,
    get_destination,
)
from dss5105.decision.ranking import (
    calculate_suitability_score,
)


FACULTY_CODE = "SOC"


def main():

    destination = get_destination(
        FACULTY_CODE
    )

    if destination is None:
        raise RuntimeError(
            "Destination not found."
        )

    listings = get_candidate_pool(
        max_budget=2000,
        limit=5,
    )

    results = []

    for listing in listings:

        commute = get_cached_commute(
            listing_id=listing["listing_id"],
            destination_id=destination[
                "destination_id"
            ],
            travel_mode="transit",
        )

        commute_minutes = None

        if commute is not None:
            commute_minutes = commute[
                "duration_min"
            ]

        ranking = (
            calculate_suitability_score(
                listing,
                max_budget=2000,
                commute_minutes=commute_minutes,
                preferred_furnishing=(
                    "fully_furnished"
                ),
                preferred_property_type=(
                    "hdb_flat"
                ),
            )
        )

        results.append(
            {
                "listing": listing,
                "commute_minutes": (
                    commute_minutes
                ),
                "ranking": ranking,
            }
        )

    results.sort(
        key=lambda item: -(
            item["ranking"]["score"]
            if item["ranking"]["score"]
            is not None
            else -1
        )
    )

    print(
        "=== Ranking V2: SOC ==="
    )

    for index, item in enumerate(
        results,
        start=1,
    ):
        listing = item["listing"]
        ranking = item["ranking"]

        print(f"\n#{index}")

        print(
            listing["listing_id"],
            "-",
            listing["title"],
        )

        print(
            "Rent:",
            listing[
                "effective_rent_monthly_sgd"
            ],
        )

        print(
            "Commute:",
            item["commute_minutes"],
            "min",
        )

        print(
            "Score:",
            ranking["score"],
        )

        print(
            "Components:",
            ranking["components"],
        )


if __name__ == "__main__":
    main()