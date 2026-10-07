from pprint import pprint

from dss5105.database.repository import (
    get_listing_by_id,
    get_listing_with_metadata,
    search_listings,
)


def main():
    print("\n=== Test 1: get_listing_by_id ===")

    listing = get_listing_by_id("500253628")
    pprint(listing)

    print("\n=== Test 2: search_listings ===")

    results = search_listings(
        max_budget=2000,
        rental_scope="room",
        limit=5,
    )

    print(f"Found {len(results)} results.")

    for result in results:
        pprint(result)

    print("\n=== Test 3: get_listing_with_metadata ===")

    full_listing = get_listing_with_metadata("500253628")
    pprint(full_listing)


if __name__ == "__main__":
    main()