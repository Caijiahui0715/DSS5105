from dss5105.commute.onemap import (
    extract_route_summary,
    get_route,
)
from dss5105.database.repository import (
    get_listing_with_metadata,
)
from dss5105.database.connection import (
    get_connection,
)


TEST_LISTING_ID = "500253628"
TEST_FACULTY_CODE = "SOC"


def get_destination(
    faculty_code: str,
) -> dict:
    """
    Retrieve one NUS representative destination.
    """

    query = """
        SELECT
            destination_id,
            faculty_code,
            faculty_name,
            destination_name,
            latitude,
            longitude
        FROM nus_destinations
        WHERE faculty_code = %s
          AND is_default = TRUE;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                query,
                (faculty_code,),
            )

            row = cur.fetchone()

            if row is None:
                raise RuntimeError(
                    f"No destination found for "
                    f"{faculty_code}"
                )

            columns = [
                desc.name
                for desc in cur.description
            ]

            return dict(zip(columns, row))


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

    print("=== Origin ===")
    print(
        listing["listing_id"],
        listing["title"],
    )
    print(
        listing["latitude"],
        listing["longitude"],
    )

    print("\n=== Destination ===")
    print(
        destination["faculty_code"],
        destination["destination_name"],
    )
    print(
        destination["latitude"],
        destination["longitude"],
    )

    route = get_route(
        start_lat=listing["latitude"],
        start_lon=listing["longitude"],
        end_lat=destination["latitude"],
        end_lon=destination["longitude"],
        route_type="pt",
    )

    print("\n=== Raw Response ===")
    print(route)

    summary = extract_route_summary(
        route
    )

    print("\n=== Parsed Summary ===")
    print(summary)


if __name__ == "__main__":
    main()