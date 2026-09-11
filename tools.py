import json
import sqlite3

from models import (
    Listing,
    RankingResult,
    RelaxationSuggestion,
    RestrictionSummary,
    SearchPreferences,
)
from onemap import OneMapNotFound, calculate_mrt_walk, load_token


_PRIORITY_BOOST = 7 / 3

_RANKING_CRITERIA = {
    "price": (
        1.0,
        lambda listing, preferences: _ratio(
            listing.get("price_sgd"), preferences.max_price_sgd
        ),
    ),
    "mrt": (
        1.0,
        lambda listing, preferences: _ratio(
            listing.get("mrt_walk_minutes")
            if listing.get("mrt_walk_minutes") is not None
            else listing.get("mrt_minutes_reported"),
            preferences.max_mrt_minutes,
        ),
    ),
}


_TEXT_RULES = {
    "cooking": (
        ("no cooking", "not_allowed"),
        ("light cooking", "limited"),
        ("cooking allowed twice", "limited"),
        ("cooking allowed", "allowed"),
    ),
    "owner_staying": (
        ("no owner staying", "no"),
        ("owner staying", "yes"),
    ),
    "tenant_gender": (
        ("female tenant only", "female_only"),
        ("male tenant preferred", "male_preferred"),
    ),
    "visitors": (
        ("visitors not allowed", "not_allowed"),
        ("no visitors", "not_allowed"),
    ),
    "smoking": (("no smoking", "not_allowed"),),
}


def load_listings(connection: sqlite3.Connection) -> list[Listing]:
    """Load all listings from a SQLite connection."""
    return _query(connection, "SELECT * FROM listings")


def search_listings(
    connection: sqlite3.Connection,
    preferences: SearchPreferences,
) -> list[Listing]:
    """Return active, valid listings satisfying every supplied constraint."""
    clauses = [
        "listing_status_code = 'ACT'",
        "instr(review_flags, '\"negative_numeric\"') = 0",
    ]
    params: list[object] = []
    filters = (
        ("price_sgd <= ?", preferences.max_price_sgd),
        ("trim(room_type) = ? COLLATE NOCASE", _clean(preferences.room_type)),
        ("trim(district_code) = ? COLLATE NOCASE", _clean(preferences.district_code)),
        (
            "COALESCE(mrt_walk_minutes, mrt_minutes_reported) <= ?",
            preferences.max_mrt_minutes,
        ),
        ("platform_verified = ?", True if preferences.verified_only else None),
    )

    for clause, value in filters:
        if value is not None:
            clauses.append(clause)
            params.append(value)

    return _query(
        connection,
        f"SELECT * FROM listings WHERE {' AND '.join(clauses)}",
        params,
    )


def refresh_mrt_walk_data(
    connection: sqlite3.Connection,
    token: str | None = None,
) -> dict[str, list[str]]:
    """Calculate and persist missing OneMap walking metrics for active listings."""
    rows = connection.execute(
        """
        SELECT listing_id, address, mrt_station
        FROM listings
        WHERE listing_status_code = 'ACT'
          AND address IS NOT NULL AND trim(address) <> ''
          AND mrt_station IS NOT NULL AND trim(mrt_station) <> ''
          AND mrt_walk_minutes IS NULL
        """
    ).fetchall()
    if not rows:
        return {"updated": [], "not_found": []}

    token = token or load_token()
    updates = []
    not_found = []
    for listing_id, address, mrt_station in rows:
        try:
            result = calculate_mrt_walk(address, mrt_station, token)
        except OneMapNotFound:
            not_found.append(listing_id)
            continue
        updates.append(
            (
                result["mrt_walk_distance_m"],
                result["mrt_walk_seconds"],
                result["mrt_walk_minutes"],
                listing_id,
            )
        )

    with connection:
        connection.executemany(
            """
            UPDATE listings
            SET mrt_walk_distance_m = ?, mrt_walk_seconds = ?, mrt_walk_minutes = ?
            WHERE listing_id = ?
            """,
            updates,
        )
    return {
        "updated": [listing_id for *_, listing_id in updates],
        "not_found": not_found,
    }


def analyze_relaxations(
    connection: sqlite3.Connection,
    preferences: SearchPreferences,
) -> list[RelaxationSuggestion]:
    # ponytail: fixed steps suit the prototype; product policy can replace them later.
    candidates = (
        (
            "max_price_sgd",
            None
            if preferences.max_price_sgd is None
            else (preferences.max_price_sgd * 11 + 9) // 10,
        ),
        (
            "max_mrt_minutes",
            None
            if preferences.max_mrt_minutes is None
            else preferences.max_mrt_minutes + 5,
        ),
        ("verified_only", False if preferences.verified_only else None),
    )
    suggestions: list[RelaxationSuggestion] = []

    for field, suggested in candidates:
        if suggested is None:
            continue
        relaxed = preferences.model_copy(update={field: suggested})
        match_count = len(search_listings(connection, relaxed))
        if match_count:
            suggestions.append(
                {
                    "field": field,
                    "current": getattr(preferences, field),
                    "suggested": suggested,
                    "match_count": match_count,
                }
            )

    return suggestions


def extract_restrictions(listing: Listing) -> RestrictionSummary:
    """Extract an ordered rule match from listing text; absence stays unknown."""
    text = f"{listing.get('title', '')} {listing.get('card_text', '')}".casefold()
    return {
        name: next((result for phrase, result in rules if phrase in text), "unknown")
        for name, rules in _TEXT_RULES.items()
    }


def rank_listings(
    listings: list[Listing],
    preferences: SearchPreferences,
) -> list[RankingResult]:
    """Rank matches by normalized use of the user's stated limits."""
    ranked: list[RankingResult] = []

    for listing in listings:
        components = []
        for name, (base_weight, scorer) in _RANKING_CRITERIA.items():
            ratio = scorer(listing, preferences)
            if ratio is not None:
                boost = (
                    _PRIORITY_BOOST
                    if preferences.ranking_priority == name
                    else 1.0
                )
                components.append((name, ratio, base_weight * boost))

        total_weight = sum(weight for _, _, weight in components)
        rank_value = (
            round(sum(ratio * weight for _, ratio, weight in components) / total_weight, 3)
            if total_weight
            else None
        )
        ranked.append(
            {
                "listing": listing,
                "rank_value": rank_value,
                "factors": {
                    name: {
                        "ratio": round(ratio, 3),
                        "weight": round(weight / total_weight, 2),
                    }
                    for name, ratio, weight in components
                },
                "warnings": list(listing.get("review_flags", [])),
            }
        )

    ranked.sort(key=_rank_key)
    return ranked


def _query(
    connection: sqlite3.Connection,
    sql: str,
    params: list[object] | None = None,
) -> list[Listing]:
    cursor = connection.execute(sql, params or [])
    columns = [column[0] for column in cursor.description]
    listings = [dict(zip(columns, row)) for row in cursor.fetchall()]

    for listing in listings:
        listing["review_flags"] = json.loads(listing["review_flags"])
        if listing.get("platform_verified") is not None:
            listing["platform_verified"] = bool(listing["platform_verified"])

    return listings


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _ratio(value: object, limit: int | None) -> float | None:
    if limit is None or not isinstance(value, (int, float)):
        return None
    return value / limit


def _rank_key(result: RankingResult) -> tuple:
    listing = result["listing"]
    value = result["rank_value"]
    return (
        value is None,
        value if value is not None else 0,
        listing.get("platform_verified") is not True,
        listing.get("price_sgd") is None,
        listing.get("price_sgd") or 0,
        listing["listing_id"],
    )
