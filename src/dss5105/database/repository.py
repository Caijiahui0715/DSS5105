from typing import Any

from dss5105.database.connection import get_connection


def get_listing_by_id(listing_id: str) -> dict[str, Any] | None:
    """
    Return one listing by listing_id.
    Returns None if the listing does not exist.
    """

    query = """
        SELECT
            listing_id,
            title,
            listing_url,
            rent_monthly_sgd,
            rent_price_type,
            rental_scope,
            room_type,
            property_type,
            bedrooms,
            bathrooms,
            area_sqm,
            area_scope,
            district_code,
            address,
            mrt_station,
            mrt_distance_m,
            mrt_minutes_reported,
            mrt_operation_status,
            listed_date,
            collected_at,
            tenant_count_reported,
            tenant_gender_label,
            gender_restriction,
            gender_preference,
            cooking_policy,
            furnishing,
            landlord_lives_in,
            private_bathroom,
            air_conditioning,
            pets_policy
        FROM listings
        WHERE listing_id = %s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (listing_id,))
            row = cur.fetchone()

            if row is None:
                return None

            columns = [desc.name for desc in cur.description]
            return dict(zip(columns, row))


def search_listings(
    max_budget: float | None = None,
    district_code: str | None = None,
    rental_scope: str | None = None,
    property_type: str | None = None,
    min_bedrooms: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """
    Search listings using optional hard/structured filters.

    Null values are not guessed or imputed.
    Unknown categorical values remain explicit strings.
    """

    conditions = []
    params = []

    if max_budget is not None:
        conditions.append("l.rent_monthly_sgd <= %s")
        params.append(max_budget)

    if district_code is not None:
        conditions.append("l.district_code = %s")
        params.append(district_code)

    if rental_scope is not None:
        conditions.append("l.rental_scope = %s")
        params.append(rental_scope)

    if property_type is not None:
        conditions.append("l.property_type = %s")
        params.append(property_type)

    if min_bedrooms is not None:
        conditions.append("l.bedrooms >= %s")
        params.append(min_bedrooms)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"""
        SELECT
            l.listing_id,
            l.title,
            l.rent_monthly_sgd,
            l.rental_scope,
            l.room_type,
            l.property_type,
            l.bedrooms,
            l.bathrooms,
            l.area_sqm,
            l.district_code,
            d.district,
            l.address,
            l.mrt_station,
            l.mrt_distance_m,
            l.mrt_minutes_reported,
            l.furnishing,
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


def get_listing_with_metadata(listing_id: str) -> dict[str, Any] | None:
    """
    Return one listing together with district and metadata information.
    """

    query = """
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
        WHERE l.listing_id = %s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (listing_id,))
            row = cur.fetchone()

            if row is None:
                return None

            columns = [desc.name for desc in cur.description]
            return dict(zip(columns, row))