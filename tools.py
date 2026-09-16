import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from models import (
    Listing,
    ListingCheckSummary,
    ListingValidationResult,
    RankingResult,
    RelaxationSuggestion,
    RestrictionSummary,
    SearchPreferences,
)
from onemap import OneMapNotFound, calculate_mrt_walk, load_token


_PRIORITY_BOOST = 7 / 3
_SOFT_MRT_REFERENCE_MINUTES = 10
_LARGE_AREA_REVIEW_THRESHOLD_SQM = 10_000 * 0.09290304
_IGNORED_REVIEW_FLAGS = {
    "same_address_different_ids",
    "tenant_count_scope_unconfirmed",
}

_RANKING_CRITERIA = {
    "price": (
        1.0,
        lambda listing, preferences: _ratio(
            listing.get("rent_monthly_sgd"), preferences.max_price_sgd
        ),
    ),
    "mrt": (
        1.0,
        lambda listing, preferences: _ratio(
            listing.get("mrt_walk_minutes")
            if listing.get("mrt_walk_minutes") is not None
            else listing.get("mrt_minutes_reported"),
            _mrt_reference(preferences),
        ),
    ),
}


def load_listings(connection: sqlite3.Connection) -> list[Listing]:
    """Load the joined Agent view using the frozen V1 field names."""
    return _query(connection, "SELECT * FROM agent_listings")


def get_listings_by_ids(
    connection: sqlite3.Connection,
    listing_ids: list[str],
) -> list[Listing]:
    """Load listings in the same order as the supplied IDs."""
    listing_ids = list(dict.fromkeys(listing_ids))
    if not listing_ids:
        return []
    placeholders = ", ".join("?" for _ in listing_ids)
    by_id = {
        listing["listing_id"]: listing
        for listing in _query(
            connection,
            f"SELECT * FROM agent_listings WHERE listing_id IN ({placeholders})",
            listing_ids,
        )
    }
    return [by_id[listing_id] for listing_id in listing_ids if listing_id in by_id]


def search_listings(
    connection: sqlite3.Connection,
    preferences: SearchPreferences,
    excluded_listing_ids: list[str] | None = None,
) -> list[Listing]:
    """Return non-inactive listings satisfying every supported hard constraint."""
    clauses = [
        "(live_status <> 'inactive' OR live_checked_at IS NULL "
        "OR julianday(live_checked_at) < julianday('now', '-24 hours'))",
        "instr(review_flags, '\"negative_numeric\"') = 0",
    ]
    params: list[object] = []
    filters = (
        ("rent_monthly_sgd <= ?", preferences.max_price_sgd),
        ("room_type = ?", _enum(preferences.room_type)),
        ("rental_scope = ?", preferences.rental_scope),
        ("district_code = ? COLLATE NOCASE", _clean(preferences.district_code)),
        (
            "COALESCE(mrt_walk_minutes, mrt_minutes_reported) <= ?",
            preferences.max_mrt_minutes,
        ),
        ("bedrooms >= ? AND rental_scope <> 'room'", preferences.min_bedrooms),
        ("tenant_count_reported >= ?", preferences.occupant_count),
    )
    for clause, value in filters:
        if value is not None:
            clauses.append(clause)
            params.append(value)

    excluded_listing_ids = list(dict.fromkeys(excluded_listing_ids or []))
    if excluded_listing_ids:
        placeholders = ", ".join("?" for _ in excluded_listing_ids)
        clauses.append(f"listing_id NOT IN ({placeholders})")
        params.extend(excluded_listing_ids)

    if preferences.property_types:
        placeholders = ", ".join("?" for _ in preferences.property_types)
        clauses.append(f"property_type IN ({placeholders})")
        params.extend(preferences.property_types)

    if preferences.cooking_required:
        clauses.append("cooking_policy IN ('allowed', 'light_only')")

    return _query(
        connection,
        f"SELECT * FROM agent_listings WHERE {' AND '.join(clauses)}",
        params,
    )


def refresh_mrt_walk_data(
    connection: sqlite3.Connection,
    token: str | None = None,
) -> dict[str, list[str]]:
    """Calculate missing OneMap routes without changing the frozen listings table."""
    rows = connection.execute(
        """
        SELECT listing_id, address, mrt_station
        FROM agent_listings
        WHERE live_status <> 'inactive'
          AND address IS NOT NULL AND trim(address) <> ''
          AND mrt_station <> 'unknown' AND trim(mrt_station) <> ''
          AND mrt_walk_minutes IS NULL
        """
    ).fetchall()
    if not rows:
        return {"updated": [], "not_found": []}

    token = token or load_token()
    updates = []
    not_found = []
    checked_at = datetime.now(timezone.utc).isoformat()
    for listing_id, address, mrt_station in rows:
        try:
            result = calculate_mrt_walk(address, mrt_station, token)
        except OneMapNotFound:
            not_found.append(listing_id)
            continue
        updates.append(
            (
                listing_id,
                result["mrt_walk_distance_m"],
                result["mrt_walk_seconds"],
                result["mrt_walk_minutes"],
                checked_at,
            )
        )

    with connection:
        connection.executemany(
            """
            INSERT INTO listing_route_enrichment VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(listing_id) DO UPDATE SET
                mrt_walk_distance_m = excluded.mrt_walk_distance_m,
                mrt_walk_seconds = excluded.mrt_walk_seconds,
                mrt_walk_minutes = excluded.mrt_walk_minutes,
                checked_at = excluded.checked_at
            """,
            updates,
        )
    return {
        "updated": [listing_id for listing_id, *_ in updates],
        "not_found": not_found,
    }


def analyze_relaxations(
    connection: sqlite3.Connection,
    preferences: SearchPreferences,
    excluded_listing_ids: list[str] | None = None,
    checker=None,
    *,
    candidate_limit: int = 30,
    result_limit: int = 3,
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
    )
    suggestions: list[RelaxationSuggestion] = []
    for field, suggested in candidates:
        if suggested is None:
            continue
        relaxed = preferences.model_copy(update={field: suggested})
        listings = search_listings(connection, relaxed, excluded_listing_ids)
        validation = validate_ranked_listings(
            connection,
            rank_listings(listings, relaxed),
            checker or check_listing_url,
            candidate_limit=candidate_limit,
            result_limit=result_limit,
        )
        match_count = len(validation["ranked_listings"])
        if match_count:
            suggestions.append(
                {
                    "field": field,
                    "current": getattr(preferences, field),
                    "suggested": suggested,
                    "match_count": match_count,
                    "check_summary": validation["summary"],
                }
            )
    return suggestions


def extract_restrictions(listing: Listing) -> RestrictionSummary:
    """Read structured V1 policy fields; missing evidence stays unknown."""
    restriction = listing.get("gender_restriction")
    preference = listing.get("gender_preference")
    tenant_gender = restriction if restriction != "unknown" else (
        f"{preference}_preferred" if preference not in {None, "unknown"} else "unknown"
    )
    return {
        "cooking": listing.get("cooking_policy") or "unknown",
        "owner_staying": listing.get("landlord_lives_in") or "unknown",
        "tenant_gender": tenant_gender,
        "visitors": "unknown",
        "smoking": "unknown",
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
                boost = _PRIORITY_BOOST if preferences.ranking_priority == name else 1.0
                components.append((name, ratio, base_weight * boost))

        total_weight = sum(weight for _, _, weight in components)
        rank_value = (
            round(
                sum(ratio * weight for _, ratio, weight in components) / total_weight,
                3,
            )
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


def check_listing_url(
    listing_id: str,
    url: str,
    timeout: float = 6,
) -> dict[str, object]:
    """Classify one listing URL by HTTP result and final redirect target."""
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 SingaporeRentalAgent/0.1",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            http_status = getattr(response, "status", 200)
    except HTTPError as error:
        return {
            "status": "inactive" if error.code in {404, 410} else "unknown",
            "final_url": error.geturl(),
            "http_status": error.code,
            "error_reason": f"http_{error.code}",
        }
    except URLError as error:
        reason = "timeout" if isinstance(error.reason, TimeoutError) else "network_error"
        return {"status": "unknown", "final_url": None, "http_status": None, "error_reason": reason}
    except TimeoutError:
        return {"status": "unknown", "final_url": None, "http_status": None, "error_reason": "timeout"}
    except OSError:
        return {"status": "unknown", "final_url": None, "http_status": None, "error_reason": "network_error"}

    final_id = _listing_id_from_url(final_url)
    if final_id == listing_id:
        status = "active"
        error_reason = None
    elif final_id is not None or final_url != url:
        status = "inactive"
        error_reason = "redirected_to_another_listing"
    else:
        status = "unknown"
        error_reason = "listing_id_not_found"
    return {
        "status": status,
        "final_url": final_url,
        "http_status": http_status,
        "error_reason": error_reason,
    }


def validate_ranked_listings(
    connection: sqlite3.Connection,
    ranked: list[RankingResult],
    checker=check_listing_url,
    *,
    candidate_limit: int = 30,
    result_limit: int | None = None,
    freshness_hours: int = 24,
) -> ListingValidationResult:
    """Scan in rank order until enough displayable listings or the check cap."""
    if candidate_limit < 0 or (result_limit is not None and result_limit < 1):
        raise ValueError("candidate_limit must be nonnegative and result_limit positive")
    validated = []
    summary: ListingCheckSummary = {
        "database_match_count": len(ranked),
        "checked_count": 0,
        "active_count": 0,
        "unknown_count": 0,
        "inactive_count": 0,
        "unchecked_count": len(ranked),
    }
    # ponytail: sequential checks capped per search; parallelize if URL latency matters.
    for item in ranked[:candidate_limit]:
        listing = item["listing"]
        health = _get_listing_health(
            connection,
            listing,
            checker,
            freshness_hours,
        )
        summary["checked_count"] += 1
        summary[f"{health['status']}_count"] += 1
        if health["status"] == "inactive":
            continue
        warnings = list(item.get("warnings", []))
        if health["status"] == "unknown" and "live_status_unknown" not in warnings:
            warnings.append("live_status_unknown")
        validated.append(
            {
                **item,
                "listing": {
                    **listing,
                    "live_status": health["status"],
                    "live_checked_at": health["checked_at"],
                    "final_url": health.get("final_url"),
                    "http_status": health.get("http_status"),
                    "live_error_reason": health.get("error_reason"),
                },
                "warnings": warnings,
            }
        )
        if result_limit is not None and len(validated) >= result_limit:
            break
    summary["unchecked_count"] -= summary["checked_count"]
    return {"ranked_listings": validated, "summary": summary}


def _get_listing_health(
    connection: sqlite3.Connection,
    listing: Listing,
    checker,
    freshness_hours: int,
) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT status, checked_at, final_url, http_status, error_reason
        FROM listing_health WHERE listing_id = ?
        """,
        (listing["listing_id"],),
    ).fetchone()
    if row and _is_fresh(row[1], freshness_hours):
        return dict(zip(("status", "checked_at", "final_url", "http_status", "error_reason"), row))

    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        result = checker(listing["listing_id"], listing["listing_url"])
    except Exception:
        result = {
            "status": "unknown",
            "final_url": None,
            "http_status": None,
            "error_reason": "checker_error",
        }
    status = result.get("status")
    if status not in {"active", "inactive", "unknown"}:
        status = "unknown"
    health = {
        "status": status,
        "checked_at": checked_at,
        "final_url": result.get("final_url"),
        "http_status": result.get("http_status"),
        "error_reason": result.get("error_reason"),
    }
    with connection:
        connection.execute(
            """
            INSERT INTO listing_health
                (listing_id, status, checked_at, final_url, http_status, error_reason)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(listing_id) DO UPDATE SET
                status = excluded.status,
                checked_at = excluded.checked_at,
                final_url = excluded.final_url,
                http_status = excluded.http_status,
                error_reason = excluded.error_reason
            """,
            (
                listing["listing_id"],
                health["status"],
                health["checked_at"],
                health["final_url"],
                health["http_status"],
                health["error_reason"],
            ),
        )
    return health


def _query(
    connection: sqlite3.Connection,
    sql: str,
    params: list[object] | None = None,
) -> list[Listing]:
    cursor = connection.execute(sql, params or [])
    columns = [column[0] for column in cursor.description]
    listings = [dict(zip(columns, row)) for row in cursor.fetchall()]
    for listing in listings:
        flags = listing.get("review_flags") or "[]"
        parsed_flags = json.loads(flags) if isinstance(flags, str) else flags
        listing["review_flags"] = [
            flag
            for flag in parsed_flags
            if _keep_review_flag(listing, flag)
        ]
    return listings


def _keep_review_flag(listing: Listing, flag: str) -> bool:
    if flag in _IGNORED_REVIEW_FLAGS:
        return False
    return not (
        flag == "area_outside_review_range"
        and isinstance(listing.get("area_sqm"), (int, float))
        and listing["area_sqm"] > _LARGE_AREA_REVIEW_THRESHOLD_SQM
    )


def _is_fresh(value: str, freshness_hours: int) -> bool:
    try:
        checked_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - checked_at <= timedelta(hours=freshness_hours)


def _listing_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    matches = re.findall(r"(?<!\d)(\d{8,9})(?!\d)", urlparse(url).path)
    return matches[-1] if matches else None


def _clean(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def _enum(value: str | None) -> str | None:
    value = _clean(value)
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") if value else None


def _ratio(value: object, limit: int | None) -> float | None:
    if limit is None or not isinstance(value, (int, float)):
        return None
    return value / limit


def _mrt_reference(preferences: SearchPreferences) -> int | None:
    if preferences.max_mrt_minutes is not None:
        return preferences.max_mrt_minutes
    if preferences.ranking_priority == "mrt":
        return _SOFT_MRT_REFERENCE_MINUTES
    return None


def _rank_key(result: RankingResult) -> tuple:
    listing = result["listing"]
    value = result["rank_value"]
    return (
        value is None,
        value if value is not None else 0,
        listing.get("rent_monthly_sgd") is None,
        listing.get("rent_monthly_sgd") or 0,
        listing["listing_id"],
    )
