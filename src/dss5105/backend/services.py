from typing import Any

from dss5105.database.connection import get_connection
from dss5105.decision.constraints import evaluate_hard_constraints


def get_candidate_pool(
    *,
    max_budget: float | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Retrieve a broad candidate pool from the database.

    Only constraints that are safe to filter deterministically
    at the SQL layer should be applied here.
    """

    conditions = []
    params = []

    if max_budget is not None:
        conditions.append("l.rent_monthly_sgd <= %s")
        params.append(max_budget)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            l.*,
            d.district,
            m.availability_status,
            m.review_flags
        FROM listings l
        JOIN district_lookup d
            ON l.district_code = d.district_code
        JOIN listing_metadata m
            ON l.listing_id = m.listing_id
        {where_clause}
        ORDER BY l.rent_monthly_sgd ASC
        LIMIT %s;
    """

    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            columns = [desc.name for desc in cur.description]

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
    Retrieve candidate listings and classify them using
    three-state hard constraint logic.

    Returns:
        {
            "pass": [...],
            "needs_confirmation": [...],
            "fail": [...]
        }
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

        results[evaluation["status"]].append(record)

    return results