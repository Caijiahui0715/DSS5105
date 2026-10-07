import sys
import time

from dss5105.backend.services import get_candidate_pool
from dss5105.commute.service import calculate_and_cache_commute


REQUEST_DELAY_SECONDS = 0.3


def main():
    if len(sys.argv) < 2:
        raise RuntimeError(
            "Please provide a faculty code.\n"
            "Example:\n"
            "uv run python -m dss5105.commute.batch_cache SOC"
        )

    faculty_code = sys.argv[1].upper()

    listings = get_candidate_pool(
        max_budget=None,
        limit=1000,
    )

    print(
        f"=== Cache Commutes for "
        f"{faculty_code} ==="
    )

    print(
        f"Active listings retrieved: "
        f"{len(listings)}"
    )

    successful = 0
    failed = 0
    missing_coordinates = 0

    failures = []

    for index, listing in enumerate(
        listings,
        start=1,
    ):
        listing_id = listing["listing_id"]
        title = listing["title"]

        print(
            f"[{index}/{len(listings)}] "
            f"{listing_id} - {title}"
        )

        if (
            listing.get("latitude") is None
            or listing.get("longitude") is None
        ):
            print(
                "  SKIPPED: missing coordinates"
            )

            missing_coordinates += 1
            continue

        try:
            result = calculate_and_cache_commute(
                listing=listing,
                faculty_code=faculty_code,
                force_refresh=False,
            )

            print(
                f"  {result['duration_min']} min, "
                f"{result['distance_m']} m"
            )

            successful += 1

        except Exception as exc:
            print(
                f"  FAILED: {exc}"
            )

            failed += 1

            failures.append(
                {
                    "listing_id": listing_id,
                    "error": str(exc),
                }
            )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    print()
    print(
        f"=== Batch Summary: "
        f"{faculty_code} ==="
    )

    print(
        f"Successful: {successful}"
    )

    print(
        f"Missing coordinates: "
        f"{missing_coordinates}"
    )

    print(
        f"Failed: {failed}"
    )

    if failures:
        print()
        print(
            "=== Failed Listings ==="
        )

        for item in failures:
            print(
                item["listing_id"],
                "-",
                item["error"],
            )


if __name__ == "__main__":
    main()