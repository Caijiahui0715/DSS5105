from pprint import pprint

from dss5105.database.repository import get_listing_by_id
from dss5105.decision.constraints import evaluate_hard_constraints


def main():
    listing = get_listing_by_id("500253628")

    print("=== Listing ===")
    pprint(listing)

    print("\n=== Hard constraint evaluation ===")

    result = evaluate_hard_constraints(
        listing,
        max_budget=2000,
        rental_scope="room",
        min_bedrooms=1,
    )

    pprint(result)


if __name__ == "__main__":
    main()