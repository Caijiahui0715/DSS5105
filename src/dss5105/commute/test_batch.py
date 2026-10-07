from dss5105.backend.services import (
    get_candidate_pool,
)
from dss5105.commute.service import (
    calculate_and_cache_commute,
)


TEST_FACULTY_CODE = "SOC"


def main():

    listings = get_candidate_pool(
        max_budget=2000,
        limit=5,
    )

    print(
        f"=== Batch Commute Test: "
        f"{TEST_FACULTY_CODE} ==="
    )

    for index, listing in enumerate(
        listings,
        start=1,
    ):
        print(
            f"\n[{index}/5] "
            f"{listing['listing_id']} "
            f"- {listing['title']}"
        )

        try:
            result = (
                calculate_and_cache_commute(
                    listing=listing,
                    faculty_code=TEST_FACULTY_CODE,
                    force_refresh=True,
                )
            )

            print(
                f"Rent: "
                f"{listing['effective_rent_monthly_sgd']}"
            )

            print(
                f"Distance: "
                f"{result['distance_m']} m"
            )

            print(
                f"Duration: "
                f"{result['duration_min']} min"
            )

            print(
                f"Benchmark: "
                f"{result['benchmark_date']} "
                f"{result['benchmark_time']}"
            )

        except Exception as exc:
            print(
                f"FAILED: {exc}"
            )


if __name__ == "__main__":
    main()