from dss5105.backend.recommendation_service import (
    recommend_listings,
)


def main():

    recommendations = recommend_listings(
        faculty_code="SOC",
        max_budget=2000,
        rental_scope="room",
        min_bedrooms=None,
        preferred_furnishing="fully_furnished",
        preferred_property_type="hdb_flat",
        limit=10,
    )

    print(
        "=== Top Recommendations ==="
    )

    for index, item in enumerate(
        recommendations,
        start=1,
    ):
        print()
        print(f"#{index}")

        print(
            item["listing_id"],
            "-",
            item["title"],
        )

        print(
            "Rent:",
            item["rent_monthly_sgd"],
        )

        print(
            "Commute:",
            item["commute_minutes"],
            "min",
        )

        print(
            "Commute status:",
            item["commute_status"],
        )

        print(
            "Constraint:",
            item["constraint_status"],
        )

        print(
            "Score:",
            item["suitability_score"],
        )

        print(
            "Score weight used:",
            item["score_weight_used"],
        )

        print(
            "Components:",
            item["score_components"],
        )

        print(
            "Review flags:",
            item["review_flags"],
        )

        print(
            "Reasons:",
            item["recommendation_reasons"],
        )


if __name__ == "__main__":
    main()