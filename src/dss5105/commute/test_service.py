from pprint import pprint

from dss5105.commute.service import (
    calculate_and_cache_commute,
    get_cached_commute,
    get_destination,
)
from dss5105.database.repository import (
    get_listing_with_metadata,
)


TEST_LISTING_ID = "500253628"
TEST_FACULTY_CODE = "SOC"


def main():

    listing = get_listing_with_metadata(
        TEST_LISTING_ID
    )

    if listing is None:
        raise RuntimeError(
            "Test listing not found."
        )

    destination = get_destination(
        TEST_FACULTY_CODE
    )

    if destination is None:
        raise RuntimeError(
            "Test destination not found."
        )

    print(
        "=== Calculate and Save ==="
    )

    result = calculate_and_cache_commute(
        listing=listing,
        faculty_code=TEST_FACULTY_CODE,
        force_refresh=True,
    )

    pprint(result)

    print(
        "\n=== Read From Cache ==="
    )

    cached = get_cached_commute(
        listing_id=TEST_LISTING_ID,
        destination_id=destination[
            "destination_id"
        ],
        travel_mode="transit",
    )

    pprint(cached)


if __name__ == "__main__":
    main()