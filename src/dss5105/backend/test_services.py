from dss5105.backend.services import find_candidates


def main():
    results = find_candidates(
        max_budget=2000,
        rental_scope="room",
        min_bedrooms=1,
        limit=100,
    )

    print("=== Candidate Summary ===")
    print("PASS:", len(results["pass"]))
    print("NEEDS_CONFIRMATION:", len(results["needs_confirmation"]))
    print("FAIL:", len(results["fail"]))

    print("\n=== Example PASS ===")
    if results["pass"]:
        record = results["pass"][0]
        print(record["listing"]["listing_id"])
        print(record["listing"]["title"])
        print(record["evaluation"])

    print("\n=== Example NEEDS_CONFIRMATION ===")
    if results["needs_confirmation"]:
        record = results["needs_confirmation"][0]
        print(record["listing"]["listing_id"])
        print(record["listing"]["title"])
        print(record["evaluation"])

    print("\n=== Example FAIL ===")
    if results["fail"]:
        record = results["fail"][0]
        print(record["listing"]["listing_id"])
        print(record["listing"]["title"])
        print(record["evaluation"])


if __name__ == "__main__":
    main()