import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from math import asin, cos, isfinite, radians, sin, sqrt
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from models import (
    AMENITY_FIELDS,
    Listing,
    ListingCheckSummary,
    ListingValidationResult,
    RankingResult,
    RelaxationSuggestion,
    RestrictionSummary,
    SearchPreferences,
)
from faculties import find_faculty
from group_db import Database
from onemap import OneMapNotFound, calculate_mrt_walk, geocode_location, load_token


# Named ranking priorities share 70% of the weight equally; the other factors share the rest.
_PRIORITY_WEIGHT = 0.7
# The ranking factor behind a priority name, where the two differ.
_PRIORITY_FACTOR = {"amenities": "food"}
_SOFT_MRT_REFERENCE_MINUTES = 10
# Listing cards convert walking distance to minutes at about 85 m per minute.
_METRES_PER_MINUTE = 85
_SOFT_COMMUTE_REFERENCE_MINUTES = 45
# Tenant gender each household can rent under; "mixed" is a male-female group such as a couple.
TENANT_GENDER_ACCEPTS = {
    "female": ("female_only", "no_restriction"),
    "male": ("male_only", "no_restriction"),
    "mixed": ("no_restriction",),
}
FURNISHED = ("fully_furnished", "partially_furnished", "furnished_unspecified")
# Unrelated people any whole unit may be let to: the lowest standing cap for private homes and
# HDB flats of three rooms or more (URA / HDB). Listings rarely state their own limit.
MAX_LEGAL_OCCUPANTS = 6
_LARGE_AREA_REVIEW_THRESHOLD_SQM = 10_000 * 0.09290304
_IGNORED_REVIEW_FLAGS = {
    "same_address_different_ids",
    "tenant_count_scope_unconfirmed",
}

_FOOD_RANK = "food_rank"

# Ranking factors, in tie-break order for factors of equal weight: each returns a ratio
# where lower is better, or None when the listing lacks the data.
_RANKING_CRITERIA = {
    "mrt": lambda listing, preferences: _ratio(mrt_distance_m(listing), _mrt_reference_m(preferences)),
    "commute": lambda listing, preferences: _ratio(commute_minutes(listing, preferences), _commute_reference(preferences)),
    "food": lambda listing, preferences: listing.get(_FOOD_RANK),
    "space": lambda listing, preferences: listing.get("space_rank"),
    "price": lambda listing, preferences: _ratio(listing.get("rent_monthly_sgd"), preferences.max_price_sgd),
}
# Missing data scores as the reference (a 10-minute walk, the commute limit) or the middle
# food position, so a listing neither gains nor loses on a factor it does not state.
_NEUTRAL_RATIO = {"mrt": 1.0, "commute": 1.0, "food": 0.5, "space": 0.5}
_RANKING_CRITERIA.update({
    name: lambda listing, preferences, name=name: listing.get(f"{name}_rank")
    for name in AMENITY_FIELDS
})
_RANKING_CRITERIA["school_distance"] = lambda listing, preferences: _ratio(
    listing.get("pg_school_nearest_walk_min"), max(preferences.max_school_walk_minutes if preferences.max_school_walk_minutes is not None else 10, 1)
)
_NEUTRAL_RATIO.update({name: 0.5 for name in AMENITY_FIELDS})
_NEUTRAL_RATIO["school_distance"] = 1.0

# Each new condition is evaluated once here, shared by strict search and three-state diagnostics.
EXTRA_CONDITION_LABELS = {
    "min_bathrooms": ("最少卫生间数", "minimum bathrooms"),
    "private_bathroom_required": ("独立卫浴", "private bathroom"),
    "pets_allowed_required": ("允许宠物", "pets allowed"),
    "rent_price_types": ("报价性质", "price types"),
    "title_keyword": ("小区/项目名称", "development/title"),
    "address_keyword": ("地址关键词", "address text"),
    "street_name": ("街道", "street"),
    "postcode": ("邮编", "postcode"),
    "nearby_location": ("指定地点直线范围", "straight-line radius from a place"),
    "mrt_station": ("最近运营 MRT 站", "nearest operating MRT station"),
    "min_mrt_stations": ("周边 MRT 站数", "reported nearby MRT count"),
    "max_mrt_distance_m": ("MRT 步行上限（米）", "MRT walking limit (metres)"),
    "min_food_places": ("1 公里内最少餐饮数", "minimum F&B within 1 km"),
    "min_hawker_centres": ("1 公里内最少小贩中心数", "minimum hawker centres within 1 km"),
    "min_libraries": ("1 公里内最少图书馆数", "minimum libraries within 1 km"),
    "min_sports_facilities": ("1 公里内最少体育设施数", "minimum sports facilities within 1 km"),
    "min_healthcare_places": ("1 公里内最少医疗设施数", "minimum healthcare places within 1 km"),
    "min_community_centres": ("1 公里内最少民众俱乐部数", "minimum community clubs within 1 km"),
    "min_schools": ("周边最少学校数", "minimum nearby schools"),
    "max_school_walk_m": ("最近学校步行上限（米）", "nearest-school walking limit (metres)"),
    "max_school_walk_minutes": ("最近学校步行上限（分钟）", "nearest-school walking limit (minutes)"),
    "listed_after": ("最早挂牌日期", "posted on or after"),
    "furnishing_types": ("家具程度", "furnishing levels"),
    "cooking_level": ("烹饪强度", "cooking level"),
    "gender_preference": ("房东明确偏好的租客性别", "advertised preferred tenant gender"),
    "lease_months": ("签约租期（月）", "lease length (months)"),
}
_MINIMUM_COLUMNS = {
    "min_bathrooms": "bathrooms", "min_mrt_stations": "pg_mrt_count",
    "min_food_places": "poi_fnb_1km", "min_hawker_centres": "poi_hawker_1km",
    "min_libraries": "poi_library_1km", "min_sports_facilities": "poi_sport_1km",
    "min_healthcare_places": "poi_healthcare_1km", "min_community_centres": "poi_community_1km",
    "min_schools": "pg_school_count",
}
_MAXIMUM_COLUMNS = {"max_school_walk_m": "pg_school_nearest_walk_m", "max_school_walk_minutes": "pg_school_nearest_walk_min"}


def extra_condition_status(field: str, listing: Listing, preferences: SearchPreferences) -> str:
    wanted = getattr(preferences, field)
    if field == "lease_months":
        # Whether the user can sign a lease of this many months: a stated term is the shortest the
        # landlord accepts, and a longer lease fits it. A short-term listing may not take a long lease.
        term = lease_term(listing)
        if term is None or (term == "short_term" and wanted >= 12):
            return "unknown"
        return "pass" if term in ("flexible", "short_term") or term <= wanted else "fail"
    if field in _MINIMUM_COLUMNS:
        value = listing.get(_MINIMUM_COLUMNS[field])
        matches = value is not None and value >= wanted
    elif field in _MAXIMUM_COLUMNS or field == "max_mrt_distance_m":
        value = mrt_distance_m(listing) if field == "max_mrt_distance_m" else listing.get(_MAXIMUM_COLUMNS[field])
        matches = value is not None and value <= wanted
    elif field == "nearby_location":
        distance = location_distance_m(listing, wanted)
        if distance is None:
            return "unknown"
        error = coordinate_error_m(listing)
        if error is None:
            return "unknown"
        if distance + error <= wanted.radius_m:
            return "pass"
        return "fail" if distance - error > wanted.radius_m else "unknown"
    elif field == "listed_after":
        try:
            value = date.fromisoformat(str(listing.get("listed_date"))[:10])
        except ValueError:
            value = None
        matches = value is not None and value >= wanted
    elif field in {"title_keyword", "address_keyword", "street_name", "postcode", "mrt_station"}:
        column = {"title_keyword": "title", "address_keyword": "address"}.get(field, field)
        value = _stated_value(listing.get(column))
        if field == "mrt_station" and listing.get("mrt_operation_status") == "under_construction":
            value = None
        matches = value is not None and (value == wanted if field == "postcode" else wanted.casefold() in value.casefold())
    else:
        column = {"private_bathroom_required": "private_bathroom", "pets_allowed_required": "pets_policy", "rent_price_types": "rent_price_type", "furnishing_types": "furnishing", "cooking_level": "cooking_policy"}.get(field, field)
        value = _stated_value(listing.get(column))
        accepted = {
            "private_bathroom_required": ("yes",), "pets_allowed_required": ("allowed", "pets_allowed"),
            "rent_price_types": wanted, "furnishing_types": wanted,
            "cooking_level": {"light": ("light_only", "allowed"), "full": ("allowed",), "none": ("not_allowed",)}.get(wanted) if field == "cooking_level" else (),
            "gender_preference": (wanted,),
        }[field]
        if field == "furnishing_types" and value == "furnished_unspecified" and value not in accepted:
            return "unknown" if {"fully_furnished", "partially_furnished"} & set(accepted) else "fail"
        matches = value is not None and value in accepted
    return "unknown" if value is None else "pass" if matches else "fail"


def _stated_value(value):
    return None if value in (None, "", "unknown") else value


def lease_term(listing: Listing) -> int | str | None:
    """The advert's lease term: months for a fixed term ("2 years" is 24), "flexible", "short_term",
    or None when not stated ("Prefer not to say" included)."""
    text = (_stated_value(listing.get("lease_term")) or "").strip().casefold()
    if text in ("flexible", "short term"):
        return text.replace(" ", "_")
    match = re.fullmatch(r"(\d+)\s*(year|month)s?", text)
    return int(match[1]) * (12 if match[2] == "year" else 1) if match else None


@lru_cache(maxsize=128)
def _location_coordinates(query: str) -> tuple[float, float]:
    # A recorded NUS faculty needs no lookup; OneMap would find several buildings for most of them.
    faculty = find_faculty(query)
    return (faculty["latitude"], faculty["longitude"]) if faculty else geocode_location(query)


def resolve_search_location(preferences: SearchPreferences) -> SearchPreferences:
    location = preferences.nearby_location
    if location is not None and location.latitude is None:
        latitude, longitude = _location_coordinates(location.query)
        location = type(location).model_validate({**location.model_dump(), "latitude": latitude, "longitude": longitude})
        return preferences.model_copy(update={"nearby_location": location})
    return preferences


def location_distance_m(listing: Listing, location) -> float | None:
    latitude, longitude = listing.get("latitude"), listing.get("longitude")
    if latitude is None or longitude is None or location.latitude is None:
        return None
    start, end = radians(location.latitude), radians(latitude)
    haversine = sin((end - start) / 2) ** 2 + cos(start) * cos(end) * sin(radians(longitude - location.longitude) / 2) ** 2
    return 6_371_008.8 * 2 * asin(sqrt(min(1, max(0, haversine))))


def coordinate_error_m(listing: Listing) -> float | None:
    value = listing.get("coord_error_m")
    if value is None:
        return 0 if listing.get("coord_source") in {None, "onemap_postcode"} else None
    try:
        error = float(str(value).lstrip("~≈"))
    except ValueError:
        return None
    return error if isfinite(error) and error >= 0 else None


def rent_percentile_sgd(connection: Database, share: float) -> float | None:
    """The monthly rent that this share of listings stays at or below."""
    rents = [row["rent_monthly_sgd"] for row in connection.query(
        "SELECT rent_monthly_sgd FROM agent_listings WHERE rent_monthly_sgd IS NOT NULL ORDER BY rent_monthly_sgd"
    )]
    return rents[min(int(len(rents) * share), len(rents) - 1)] if rents else None


def load_listings(connection: Database) -> list[Listing]:
    """Load the joined Agent view using the frozen V1 field names."""
    return _query(connection, "TRUE")


def get_listings_by_ids(
    connection: Database,
    listing_ids: list[str],
) -> list[Listing]:
    """Load listings in the same order as the supplied IDs."""
    listing_ids = list(dict.fromkeys(listing_ids))
    if not listing_ids:
        return []
    by_id = {
        listing["listing_id"]: listing
        for listing in _query(connection, "listing_id = ANY(%s)", [listing_ids])
    }
    return [by_id[listing_id] for listing_id in listing_ids if listing_id in by_id]


def search_listings(
    connection: Database,
    preferences: SearchPreferences,
    excluded_listing_ids: list[str] | None = None,
) -> list[Listing]:
    """Return non-inactive listings satisfying every supported hard constraint."""
    preferences = resolve_search_location(preferences)
    clauses = [
        "(live_status <> 'inactive' OR live_checked_at IS NULL "
        "OR live_checked_at::timestamptz < now() - interval '24 hours')",
        "NOT 'negative_numeric' = ANY(review_flags)",
    ]
    params: list[object] = []
    filters = (
        ("rent_monthly_sgd <= %s", preferences.max_price_sgd),
        ("room_type = %s", _enum(preferences.room_type)),
        ("rental_scope = %s", preferences.rental_scope),
        ("lower(district_code) = lower(%s)", _clean(preferences.district_code)),
        (
            "COALESCE(mrt_walk_minutes, mrt_minutes_reported) <= %s "
            "AND mrt_operation_status <> 'under_construction'",
            preferences.max_mrt_minutes,
        ),
        ("bedrooms >= %s AND rental_scope <> 'room'", preferences.min_bedrooms),
        ("area_sqm >= %s AND space_rank IS NOT NULL", preferences.min_area_sqm),
    )
    for clause, value in filters:
        if value is not None:
            clauses.append(clause)
            params.append(value)
    # Occupants meet a whole unit up to the legal cap, and a room only for one person: a room's
    # "N pax" label may count the whole flat (decision.condition_status).
    if (people := preferences.occupant_count) is not None:
        clauses.append(
            "rental_scope IN ('entire_unit', 'room')" if people == 1
            else "rental_scope = 'entire_unit'" if people <= MAX_LEGAL_OCCUPANTS
            else "FALSE"
        )

    excluded_listing_ids = list(dict.fromkeys(excluded_listing_ids or []))
    if excluded_listing_ids:
        clauses.append("listing_id <> ALL(%s)")
        params.append(excluded_listing_ids)

    if preferences.property_types:
        clauses.append("property_type = ANY(%s)")
        params.append(list(preferences.property_types))

    accepted = (
        ("gender_restriction", TENANT_GENDER_ACCEPTS.get(preferences.tenant_gender)),
        ("cooking_policy", ("allowed", "light_only") if preferences.cooking_required else None),
        ("landlord_lives_in", ("no",) if preferences.landlord_not_living_in else None),
        ("furnishing", FURNISHED if preferences.furnished_required else None),
        ("air_conditioning", ("yes",) if preferences.air_conditioning_required else None),
    )
    for column, values in accepted:
        if values:
            clauses.append(f"{column} = ANY(%s)")
            params.append(list(values))
    # Each named ranking priority needs its data, as in decision.search_with_unknowns().
    priority_data = {
        "mrt": "COALESCE(mrt_walk_distance_m, mrt_distance_m) IS NOT NULL "
        "AND mrt_operation_status <> 'under_construction'",
        "amenities": f"{_FOOD_RANK} IS NOT NULL",
        "space": "space_rank IS NOT NULL",
        **{name: f"{name}_rank IS NOT NULL" for name in AMENITY_FIELDS},
        "school_distance": "pg_school_nearest_walk_min IS NOT NULL",
    }
    clauses.extend(priority_data[name] for name in preferences.ranking_priority if name in priority_data)

    candidates = _query(connection, " AND ".join(clauses), params)
    active = [field for field in EXTRA_CONDITION_LABELS if getattr(preferences, field) != SearchPreferences.model_fields[field].default]
    # ponytail: Python filtering is sufficient for this 519-row prototype; use SQL at larger scale.
    candidates = [listing for listing in candidates if all(extra_condition_status(field, listing, preferences) == "pass" for field in active)]
    # Commutes depend on the user's faculty, so they are checked here rather than in SQL.
    if preferences.max_commute_minutes is not None or "commute" in preferences.ranking_priority:
        limit = preferences.max_commute_minutes
        candidates = [
            listing
            for listing in candidates
            if (minutes := commute_minutes(listing, preferences)) is not None and (limit is None or minutes <= limit)
        ]
    return candidates


def commute(listing: Listing, faculty: str | None) -> dict | None:
    """The trip from the listing to a faculty, {"minutes", "mode"} with mode transit or walk."""
    return (listing.get("commutes") or {}).get(faculty) if faculty else None


def commute_minutes(listing: Listing, preferences: SearchPreferences) -> float | None:
    """Minutes from the listing to the user's faculty, when both are known."""
    trip = commute(listing, preferences.faculty)
    return trip["minutes"] if trip else None


def refresh_mrt_walk_data(
    connection: Database,
    token: str | None = None,
) -> dict[str, list[str]]:
    """Calculate missing OneMap routes without changing the frozen listings table."""
    rows = connection.query(
        """
        SELECT listing_id, address, mrt_station
        FROM agent_listings
        WHERE live_status <> 'inactive'
          AND address IS NOT NULL AND trim(address) <> ''
          AND mrt_station <> 'unknown' AND trim(mrt_station) <> ''
          AND mrt_walk_minutes IS NULL
        ORDER BY listing_id
        """
    )
    if not rows:
        return {"updated": [], "not_found": []}

    token = token or load_token()
    updates = []
    not_found = []
    checked_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        listing_id = row["listing_id"]
        try:
            result = calculate_mrt_walk(row["address"], row["mrt_station"], token)
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

    for update in updates:
        connection.run(
            """
            INSERT INTO listing_route_enrichment VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (listing_id) DO UPDATE SET
                mrt_walk_distance_m = EXCLUDED.mrt_walk_distance_m,
                mrt_walk_seconds = EXCLUDED.mrt_walk_seconds,
                mrt_walk_minutes = EXCLUDED.mrt_walk_minutes,
                checked_at = EXCLUDED.checked_at
            """,
            update,
        )
    return {
        "updated": [listing_id for listing_id, *_ in updates],
        "not_found": not_found,
    }


def analyze_relaxations(
    connection: Database,
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
        # Signing for longer: a 1-year lease, then a 2-year one, the terms most listings ask for.
        *(
            ("lease_months", months)
            for months in (12, 24)
            if preferences.lease_months is not None and preferences.lease_months < months
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
        "furnishing": listing.get("furnishing") or "unknown",
        "air_conditioning": listing.get("air_conditioning") or "unknown",
        "private_bathroom": listing.get("private_bathroom") or "unknown",
        "pets": listing.get("pets_policy") or "unknown",
        "visitors": "unknown",
        "smoking": "unknown",
    }


def rank_listings(
    listings: list[Listing],
    preferences: SearchPreferences,
) -> list[RankingResult]:
    """Rank matches by normalized use of the user's stated limits.

    Rent and MRT walking distance are always weighed; nearby food and the commute to the
    user's faculty only when the user asks for them. Named priorities share 70% of the weight.
    """
    names = _ranking_factors(preferences)
    weights = _factor_weights(names, preferences.ranking_priority)
    ranked: list[RankingResult] = []
    for listing in listings:
        factors = {}
        for name in names:
            ratio = _RANKING_CRITERIA[name](listing, preferences)
            if ratio is None and name in _NEUTRAL_RATIO:
                factors[name] = {"ratio": _NEUTRAL_RATIO[name], "no_data": True}
            elif ratio is not None:
                factors[name] = {"ratio": ratio}
        total_weight = sum(weights[name] for name in factors)
        rank_value = (
            round(sum(factor["ratio"] * weights[name] for name, factor in factors.items()) / total_weight, 3)
            if total_weight
            else None
        )
        for name, factor in factors.items():
            factor["ratio"] = round(factor["ratio"], 3)
            factor["weight"] = round(weights[name] / total_weight, 2)
        ranked.append(
            {
                "listing": listing,
                "rank_value": rank_value,
                "factors": factors,
                "warnings": list(listing.get("review_flags", [])),
                # For listing cards: the trip to the user's faculty, when one is saved.
                "commute": preferences.faculty and {"faculty": preferences.faculty, "minutes": None, "mode": None, **(commute(listing, preferences.faculty) or {})},
            }
        )
    ranked.sort(key=_rank_key)
    return ranked


def mrt_distance_m(listing: Listing) -> float | None:
    """Walking metres to an operating MRT station: a OneMap route first, then the listing card."""
    if listing.get("mrt_operation_status") == "under_construction":
        return None
    walked = listing.get("mrt_walk_distance_m")
    return walked if walked is not None else listing.get("mrt_distance_m") if listing.get("mrt_distance_m") is not None else listing.get("pg_mrt_nearest_walk_m")


def mrt_minutes(listing: Listing) -> int | float | None:
    """Walking minutes to an operating MRT station: a OneMap route first, then the listing card."""
    if listing.get("mrt_operation_status") == "under_construction":
        return None
    walked = listing.get("mrt_walk_minutes")
    return walked if walked is not None else listing.get("mrt_minutes_reported")


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
    connection: Database,
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
    connection: Database,
    listing: Listing,
    checker,
    freshness_hours: int,
) -> dict[str, object]:
    rows = connection.query(
        """
        SELECT status, checked_at, final_url, http_status, error_reason
        FROM listing_health WHERE listing_id = %s
        """,
        (listing["listing_id"],),
    )
    if rows and _is_fresh(rows[0]["checked_at"], freshness_hours):
        return rows[0]

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
    # Kept in the database, so later turns and restarts reuse it for 24 hours.
    connection.run(
        """
        INSERT INTO listing_health
            (listing_id, status, checked_at, final_url, http_status, error_reason)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (listing_id) DO UPDATE SET
            status = EXCLUDED.status,
            checked_at = EXCLUDED.checked_at,
            final_url = EXCLUDED.final_url,
            http_status = EXCLUDED.http_status,
            error_reason = EXCLUDED.error_reason
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
    connection: Database,
    where: str,
    params: list[object] | None = None,
) -> list[Listing]:
    """Listings from the agent_listings view meeting the SQL condition where, in listing_id order."""
    listings = connection.query(f"SELECT * FROM agent_listings WHERE {where} ORDER BY listing_id", params or [])
    for listing in listings:
        listing["review_flags"] = [
            flag
            for flag in listing.get("review_flags") or []
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


def rental_area_sqm(listing: Listing) -> float | None:
    """A room's advertised whole-home area does not establish the room's size."""
    area = listing.get("area_sqm")
    scope = {"entire_unit": "floor_reported", "room": "room_reported"}.get(listing.get("rental_scope"))
    return area if scope and listing.get("area_scope") == scope and isinstance(area, (int, float)) and area > 0 else None


def _ranking_factors(preferences: SearchPreferences) -> list[str]:
    priorities = preferences.ranking_priority
    asked = {
        "mrt": True,
        "commute": preferences.max_commute_minutes is not None or "commute" in priorities,
        "food": "amenities" in priorities,
        "space": "space" in priorities,
        "price": preferences.max_price_sgd is not None,
    }
    asked.update({name: name in priorities for name in (*AMENITY_FIELDS, "school_distance")})
    return [name for name in _RANKING_CRITERIA if asked[name]]


def _factor_weights(names: list[str], priorities: tuple[str, ...]) -> dict[str, float]:
    named = {_PRIORITY_FACTOR.get(priority, priority) for priority in priorities} & set(names)
    if not named or len(named) == len(names):
        return {name: 1.0 for name in names}
    each = _PRIORITY_WEIGHT / len(named)
    # The rest share 30% but never outweigh a named priority, e.g. three named and one other.
    # rank_listings() rescales the weights to sum to 1.
    rest = min((1 - _PRIORITY_WEIGHT) / (len(names) - len(named)), each)
    return {name: each if name in named else rest for name in names}


def _mrt_reference_m(preferences: SearchPreferences) -> float:
    minutes = preferences.max_mrt_minutes
    reference = max(minutes if minutes is not None else _SOFT_MRT_REFERENCE_MINUTES, 1) * _METRES_PER_MINUTE
    if preferences.max_mrt_distance_m is not None:
        reference = min(reference, preferences.max_mrt_distance_m) if minutes is not None else preferences.max_mrt_distance_m
    return max(reference, 1)


def _commute_reference(preferences: SearchPreferences) -> int:
    return max(preferences.max_commute_minutes or _SOFT_COMMUTE_REFERENCE_MINUTES, 1)


def _rank_key(result: RankingResult) -> tuple:
    """Lower scores first; ties go to the heavier factor, then the next, then rent."""
    listing = result["listing"]
    value = result["rank_value"]
    order = list(_RANKING_CRITERIA)
    factors = sorted(
        result["factors"].items(),
        key=lambda item: (-item[1]["weight"], order.index(item[0])),
    )
    return (
        value is None,
        value if value is not None else 0,
        tuple(factor["ratio"] for _, factor in factors),
        listing.get("rent_monthly_sgd") is None,
        listing.get("rent_monthly_sgd") or 0,
        listing["listing_id"],
    )
