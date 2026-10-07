from typing import Any

from dss5105.database.connection import get_connection
from dss5105.decision.constraints import evaluate_hard_constraints


def get_candidate_pool(
    *,
    max_budget: float | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Retrieve a broad pool of currently active rental listings.

    Only constraints that are safe to apply deterministically at
    the SQL layer should be used here.

    Current rent is preferred over the original snapshot rent.
    """

    conditions = [
        "l.scrape_status = 'active'"
    ]

    params = []

    if max_budget is not None:
        conditions.append(
            """
            COALESCE(
                l.rent_monthly_sgd_now,
                l.rent_monthly_sgd
            ) <= %s
            """
        )
        params.append(max_budget)

    where_clause = (
        "WHERE " + " AND ".join(conditions)
    )

    query = f"""
        SELECT
            l.*,

            COALESCE(
                l.rent_monthly_sgd_now,
                l.rent_monthly_sgd
            ) AS effective_rent_monthly_sgd,

            d.district,

            m.availability_status,
            m.review_flags,

            e.enriched_at,
            e.postcode,
            e.street_name,
            e.latitude,
            e.longitude,

            e.poi_hawker_1km,
            e.poi_library_1km,
            e.poi_sport_1km,
            e.poi_healthcare_1km,
            e.poi_community_1km,
            e.poi_fnb_1km,

            e.pg_school_count,
            e.pg_school_nearest_walk_m,
            e.pg_school_nearest_walk_min,

            e.pg_mrt_count,
            e.pg_mrt_nearest_walk_m,

            e.coord_source,
            e.coord_error_m

        FROM listings l

        JOIN district_lookup d
            ON l.district_code = d.district_code

        JOIN listing_metadata m
            ON l.listing_id = m.listing_id

        LEFT JOIN listing_enrichment e
            ON l.listing_id = e.listing_id

        {where_clause}

        ORDER BY
            COALESCE(
                l.rent_monthly_sgd_now,
                l.rent_monthly_sgd
            ) ASC

        LIMIT %s;
    """

    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                tuple(params),
            )

            rows = cur.fetchall()

            columns = [
                desc.name
                for desc in cur.description
            ]

            return [
                dict(zip(columns, row))
                for row in rows
            ]


def find_candidates(
    *,
    max_budget: float | None = None,
    rental_scope: str | None = None,
    min_bedrooms: int | None = None,
    limit: int = 200,
) -> dict[str, list[dict]]:
    """
    Retrieve active listings and classify them using
    three-state hard-constraint logic.

    Returns:
        {
            "pass": [...],
            "needs_confirmation": [...],
            "fail": [...]
        }

    The database layer performs only safe pruning.
    Uncertain constraints are evaluated in Python so that
    missing information can become needs_confirmation rather
    than being silently excluded.
    """

    listings = get_candidate_pool(
        max_budget=max_budget,
        limit=limit,
    )

    results = {
        "pass": [],
        "needs_confirmation": [],
        "fail": [],
    }

    for listing in listings:
        evaluation = evaluate_hard_constraints(
            listing,
            max_budget=max_budget,
            rental_scope=rental_scope,
            min_bedrooms=min_bedrooms,
        )

        record = {
            "listing": listing,
            "evaluation": evaluation,
        }

        results[
            evaluation["status"]
        ].append(record)

    return results