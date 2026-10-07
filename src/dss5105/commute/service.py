from datetime import date, timedelta
from typing import Any

from dss5105.commute.onemap import (
    extract_route_summary,
    get_route,
)
from dss5105.database.connection import get_connection


BENCHMARK_TIME = "08:30:00"


def get_next_weekday() -> date:
    """
    Return the next Monday-Friday date.

    If today is already a weekday, use today.
    Otherwise move forward to Monday.
    """

    benchmark_date = date.today()

    while benchmark_date.weekday() >= 5:
        benchmark_date += timedelta(days=1)

    return benchmark_date


def format_onemap_date(value: date) -> str:
    """
    OneMap expects MM-DD-YYYY.
    """

    return value.strftime("%m-%d-%Y")


def get_destination(
    faculty_code: str,
) -> dict[str, Any] | None:
    """
    Return the default representative destination
    for one NUS faculty / school.
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
                return None

            columns = [
                desc.name
                for desc in cur.description
            ]

            return dict(zip(columns, row))


def save_commute(
    *,
    listing_id: str,
    destination_id: str,
    travel_mode: str,
    distance_m: int | None,
    duration_min: float | None,
    benchmark_date: date,
    benchmark_time: str,
    route_provider: str = "onemap",
) -> None:
    """
    Insert or update one commute result.
    """

    query = """
        INSERT INTO listing_commutes (
            listing_id,
            destination_id,
            travel_mode,
            distance_m,
            duration_min,
            route_provider,
            benchmark_date,
            benchmark_time,
            calculated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            CURRENT_TIMESTAMP
        )

        ON CONFLICT (
            listing_id,
            destination_id,
            travel_mode
        )

        DO UPDATE SET
            distance_m = EXCLUDED.distance_m,
            duration_min = EXCLUDED.duration_min,
            route_provider = EXCLUDED.route_provider,
            benchmark_date = EXCLUDED.benchmark_date,
            benchmark_time = EXCLUDED.benchmark_time,
            calculated_at = CURRENT_TIMESTAMP;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    listing_id,
                    destination_id,
                    travel_mode,
                    distance_m,
                    duration_min,
                    route_provider,
                    benchmark_date,
                    benchmark_time,
                ),
            )

        conn.commit()


def get_cached_commute(
    *,
    listing_id: str,
    destination_id: str,
    travel_mode: str = "transit",
) -> dict[str, Any] | None:
    """
    Return an existing cached commute result.
    """

    query = """
        SELECT
            listing_id,
            destination_id,
            travel_mode,
            distance_m,
            duration_min,
            route_provider,
            benchmark_date,
            benchmark_time,
            calculated_at
        FROM listing_commutes
        WHERE listing_id = %s
          AND destination_id = %s
          AND travel_mode = %s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    listing_id,
                    destination_id,
                    travel_mode,
                ),
            )

            row = cur.fetchone()

            if row is None:
                return None

            columns = [
                desc.name
                for desc in cur.description
            ]

            return dict(zip(columns, row))


def calculate_and_cache_commute(
    *,
    listing: dict[str, Any],
    faculty_code: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Calculate public-transport commute from one listing
    to one NUS representative destination.

    Ranking benchmark:
    weekday, 08:30 departure.
    """

    destination = get_destination(
        faculty_code
    )

    if destination is None:
        raise RuntimeError(
            f"No NUS destination found for "
            f"{faculty_code}"
        )

    if (
        listing.get("latitude") is None
        or listing.get("longitude") is None
    ):
        raise RuntimeError(
            f"Listing {listing.get('listing_id')} "
            f"has no coordinates."
        )

    destination_id = destination[
        "destination_id"
    ]

    benchmark_date = get_next_weekday()

    if not force_refresh:
        cached = get_cached_commute(
            listing_id=listing["listing_id"],
            destination_id=destination_id,
            travel_mode="transit",
        )

        if (
            cached is not None
            and cached.get("benchmark_date")
            == benchmark_date
        ):
            return cached

    route_data = get_route(
        start_lat=listing["latitude"],
        start_lon=listing["longitude"],
        end_lat=destination["latitude"],
        end_lon=destination["longitude"],
        route_type="pt",
        mode="TRANSIT",
        date=format_onemap_date(
            benchmark_date
        ),
        time=BENCHMARK_TIME,
    )

    summary = extract_route_summary(
        route_data
    )

    save_commute(
        listing_id=listing["listing_id"],
        destination_id=destination_id,
        travel_mode="transit",
        distance_m=summary["distance_m"],
        duration_min=summary["duration_min"],
        benchmark_date=benchmark_date,
        benchmark_time=BENCHMARK_TIME,
    )

    return {
        "listing_id": listing["listing_id"],
        "destination_id": destination_id,
        "travel_mode": "transit",
        "distance_m": summary["distance_m"],
        "duration_min": summary["duration_min"],
        "benchmark_date": benchmark_date,
        "benchmark_time": BENCHMARK_TIME,
        "route_provider": "onemap",
    }