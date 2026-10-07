from dss5105.backend.services import find_candidates
from dss5105.decision.ranking import rank_candidates


def main():

    candidates = find_candidates(
        max_budget=2000,
        rental_scope="room",
        min_bedrooms=None,
        limit=200,
    )

    ranked = rank_candidates(
        candidates,
        max_budget=2000,
        preferred_furnishing="fully_furnished",
        preferred_property_type="hdb_flat",
    )

    print("=== Ranking Summary ===")
    print("Total ranked:", len(ranked))

    print("\n=== Top 10 ===")

    for index, item in enumerate(
        ranked[:10],
        start=1,
    ):
        listing = item["listing"]
        ranking = item["ranking"]

        print(
            f"\n#{index}"
        )

        print(
            "Listing:",
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
            "Constraint status:",
            item["constraint_status"],
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