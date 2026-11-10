import re
from datetime import date, datetime, timezone
from functools import lru_cache
from math import asin, ceil, cos, isfinite, radians, sin, sqrt

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
    "commute": lambda listing, preferences: _commute_ratio(listing, preferences),
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
    "max_other_commute_minutes": ("到另一个目的地的通勤上限（分钟）", "commute limit to your other destination (minutes)"),
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
    if field == "max_other_commute_minutes":
        minutes = other_commute_minutes(listing, preferences)
        return "unknown" if minutes is None else "pass" if minutes <= wanted else "fail"
    if field == "lease_months":
        # Whether the user can sign a lease of this many months: a stated term is the shortest the
        # landlord accepts, and a longer lease fits it. Flexible and short-term listings accept any.
        term = lease_term(listing)
        if term is None:
            return "unknown"
        return "pass" if term in ("flexible", "short_term") or term <= wanted else "fail"
    if field == "max_mrt_distance_m":
        return mrt_limit_status(nearest_mrt_distance_m(listing), wanted, listing)
    if field in _MINIMUM_COLUMNS:
        value = listing.get(_MINIMUM_COLUMNS[field])
        matches = value is not None and value >= wanted
    elif field in _MAXIMUM_COLUMNS:
        value = listing.get(_MAXIMUM_COLUMNS[field])
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
    """Locate the places the preferences name: the nearby location, and the other destination,
    which is a recorded faculty (its commutes are worked out in advance) or a place found on OneMap."""
    update = {}
    location = preferences.nearby_location
    if location is not None and location.latitude is None:
        latitude, longitude = _location_coordinates(location.query)
        update["nearby_location"] = type(location).model_validate({**location.model_dump(), "latitude": latitude, "longitude": longitude})
    destination = preferences.other_destination
    if destination is not None and destination.latitude is None:
        faculty = find_faculty(destination.query)
        latitude, longitude = (faculty["latitude"], faculty["longitude"]) if faculty else geocode_location(destination.query)
        update["other_destination"] = destination.model_copy(
            update={"faculty": faculty and faculty["name"], "latitude": latitude, "longitude": longitude}
        )
    return preferences.model_copy(update=update) if update else preferences


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
    """Return listings satisfying every supported hard constraint."""
    preferences = resolve_search_location(preferences)
    clauses = ["NOT 'negative_numeric' = ANY(review_flags)"]
    params: list[object] = []
    filters = (
        ("rent_monthly_sgd <= %s", preferences.max_price_sgd),
        ("room_type = %s", _enum(preferences.room_type)),
        ("rental_scope = %s", preferences.rental_scope),
        ("lower(district_code) = lower(%s)", _clean(preferences.district_code)),
        (
            "COALESCE(mrt_walk_minutes, mrt_minutes_reported) <= %s "
            "AND mrt_operation_status = 'operational'",
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

    candidates = _query(connection, " AND ".join(clauses), params)
    active = [field for field in EXTRA_CONDITION_LABELS if getattr(preferences, field) != SearchPreferences.model_fields[field].default]
    # ponytail: Python filtering is sufficient for this 519-row prototype; use SQL at larger scale.
    candidates = [listing for listing in candidates if all(extra_condition_status(field, listing, preferences) == "pass" for field in active)]
    # Commutes depend on the user's faculty, so they are checked here rather than in SQL (the other
    # destination's limit is an extra condition above).
    limit = preferences.max_commute_minutes
    if limit is not None:
        candidates = [
            listing
            for listing in candidates
            if (minutes := commute_minutes(listing, preferences)) is not None and minutes <= limit
        ]
    return candidates


def own_commute_needed(preferences: SearchPreferences) -> bool:
    """Whether a search needs each listing's trip to the user's faculty: for its limit, or to rank by
    commute, unless only the other destination is known."""
    return preferences.max_commute_minutes is not None or (
        "commute" in preferences.ranking_priority and (preferences.faculty is not None or preferences.other_destination is None)
    )


def commute(listing: Listing, faculty: str | None) -> dict | None:
    """The trip from the listing to a faculty, {"minutes", "mode"} with mode transit or walk."""
    return (listing.get("commutes") or {}).get(faculty) if faculty else None


def commute_minutes(listing: Listing, preferences: SearchPreferences) -> float | None:
    """Minutes from the listing to the user's faculty, when both are known."""
    trip = commute(listing, preferences.faculty)
    return trip["minutes"] if trip else None


def place_key(latitude: float, longitude: float) -> str:
    """How routes to a place are filed (place_routes.py): its position to about a metre."""
    return f"{latitude:.5f},{longitude:.5f}"


def destination_trip(listing: Listing, destination) -> dict | None:
    """The trip from the listing to the other destination, {"minutes", "mode"}: from the faculty
    commutes for a faculty, otherwise from the routes worked out to that place."""
    if destination is None:
        return None
    if destination.faculty:
        return commute(listing, destination.faculty)
    if destination.latitude is None:
        return None
    return (listing.get("place_commutes") or {}).get(place_key(destination.latitude, destination.longitude))


def other_commute_minutes(listing: Listing, preferences: SearchPreferences) -> float | None:
    """Minutes from the listing to the other destination, when known."""
    trip = destination_trip(listing, preferences.other_destination)
    return trip["minutes"] if trip else None


def destination_view(destination) -> dict | None:
    """The other destination as replies and pages name it: the faculty it is, or the place and what
    it is to the user."""
    return destination and {"faculty": destination.faculty, "query": destination.query, "name": destination.name}


def refresh_mrt_walk_data(
    connection: Database,
    token: str | None = None,
) -> dict[str, list[str]]:
    """Calculate missing OneMap routes without changing the frozen listings table."""
    rows = connection.query(
        """
        SELECT listing_id, address, mrt_station
        FROM agent_listings
        WHERE address IS NOT NULL AND trim(address) <> ''
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


# The limits a relaxation may change, each with what a listing needs of it. A walking limit counts
# only an operating station, since any other would still not be confirmed.
_RELAXABLE = {
    "max_price_sgd": lambda listing, preferences: listing.get("rent_monthly_sgd"),
    "max_mrt_minutes": lambda listing, preferences: nearest_mrt_minutes(listing) if listing.get("mrt_operation_status") == "operational" else None,
    "max_mrt_distance_m": lambda listing, preferences: nearest_mrt_distance_m(listing) if listing.get("mrt_operation_status") == "operational" else None,
    "max_commute_minutes": lambda listing, preferences: commute_minutes(listing, preferences),
    "max_other_commute_minutes": lambda listing, preferences: other_commute_minutes(listing, preferences),
    "lease_months": lambda listing, preferences: term if isinstance(term := lease_term(listing), int) else None,
}


def analyze_relaxations(
    connection: Database,
    preferences: SearchPreferences,
    excluded_listing_ids: list[str] | None = None,
) -> list[RelaxationSuggestion]:
    """For each limit set, the smallest change that lets a listing meet every condition, if any does."""
    suggestions: list[RelaxationSuggestion] = []
    for field, needs in _RELAXABLE.items():
        current = getattr(preferences, field)
        if current is None:
            continue
        without_it = search_listings(connection, preferences.model_copy(update={field: None}), excluded_listing_ids)
        values = [value for listing in without_it if (value := needs(listing, preferences)) is not None and value > current]
        if not values:
            continue
        suggested = ceil(min(values))
        relaxed = preferences.model_copy(update={field: suggested})
        suggestions.append(
            {
                "field": field,
                "current": current,
                "suggested": suggested,
                "match_count": len(search_listings(connection, relaxed, excluded_listing_ids)),
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
    """Rank matches. Stated priorities decide strictly, in the order stated, then rent; a listing
    that does not state one comes last on it (CONVENTIONS.md section 5). Without any, MRT walking
    distance and, with a budget, rent are weighed equally.
    """
    names = _ranking_factors(preferences)
    order = ranking_order(preferences)
    ranked: list[RankingResult] = []
    for listing in listings:
        factors = {}
        for name in names:
            ratio = _RANKING_CRITERIA[name](listing, preferences)
            if ratio is None and name in _NEUTRAL_RATIO:
                factors[name] = {"ratio": _NEUTRAL_RATIO[name], "no_data": True}
            elif ratio is not None:
                factors[name] = {"ratio": ratio}
        rank_value = round(sum(factor["ratio"] for factor in factors.values()) / len(factors), 3) if factors and not order else None
        for factor in factors.values():
            factor["ratio"] = round(factor["ratio"], 3)
            if not order:
                factor["weight"] = round(1 / len(factors), 2)
        ranked.append(
            {
                "listing": listing,
                "rank_value": rank_value,
                "factors": factors,
                "ranking_order": order,
                "warnings": list(listing.get("review_flags", [])),
                # For listing cards: the trip to the user's faculty, when one is saved, and to the other destination.
                "commute": preferences.faculty and {"faculty": preferences.faculty, "minutes": None, "mode": None, **(commute(listing, preferences.faculty) or {})},
                "other_commute": preferences.other_destination and {
                    **destination_view(preferences.other_destination), "minutes": None, "mode": None,
                    **(destination_trip(listing, preferences.other_destination) or {}),
                },
            }
        )
    ranked.sort(key=(lambda item: _priority_key(item["listing"], preferences, order)) if order else _rank_key)
    return ranked


def nearest_mrt_distance_m(listing: Listing) -> float | None:
    """Walking metres to the nearest MRT station, open or not: a OneMap route first, then the listing card."""
    walked = listing.get("mrt_walk_distance_m")
    return walked if walked is not None else listing.get("mrt_distance_m") if listing.get("mrt_distance_m") is not None else listing.get("pg_mrt_nearest_walk_m")


def mrt_distance_m(listing: Listing) -> float | None:
    """Walking metres to an operating MRT station."""
    return None if listing.get("mrt_operation_status") == "under_construction" else nearest_mrt_distance_m(listing)


def nearest_mrt_minutes(listing: Listing) -> int | float | None:
    """Walking minutes to the nearest MRT station, open or not: a OneMap route first, then the listing card."""
    walked = listing.get("mrt_walk_minutes")
    return walked if walked is not None else listing.get("mrt_minutes_reported")


def mrt_minutes(listing: Listing) -> int | float | None:
    """Walking minutes to an operating MRT station."""
    return None if listing.get("mrt_operation_status") == "under_construction" else nearest_mrt_minutes(listing)


def mrt_limit_status(value: float | None, limit: float, listing: Listing) -> str:
    """Pass, fail or unknown for a walking limit to an operating station. The data gives the nearest
    station of any status: when that one is not known to operate, the nearest operating one is at
    least as far, so a value above the limit fails and any other is unknown."""
    if value is None:
        return "unknown"
    if value > limit:
        return "fail"
    return "pass" if listing.get("mrt_operation_status") == "operational" else "unknown"


# A link check older than this many days is too old to lean on: the reply says so.
LINK_CHECK_STALE_DAYS = 14


def link_check_age_days(listing: Listing, today: date | None = None) -> int | None:
    """Days since the data refresh last opened the listing's page; None when it never did."""
    checked_at = listing.get("live_checked_at")
    if not checked_at:
        return None
    return ((today or date.today()) - date.fromisoformat(str(checked_at)[:10])).days


def validate_ranked_listings(
    ranked: list[RankingResult],
    *,
    result_limit: int | None = None,
) -> ListingValidationResult:
    """The listings to show, in rank order, each flagged when its link needs the user's own check.

    The site sends no requests (PropertyGuru refuses automated ones). All that is known of a link
    is when the data refresh last opened its page, so a listing it never opened, or not for
    LINK_CHECK_STALE_DAYS, is flagged.
    """
    if result_limit is not None and result_limit < 1:
        raise ValueError("result_limit must be positive")
    validated = []
    for item in ranked[:result_limit]:
        age = link_check_age_days(item["listing"])
        warnings = list(item.get("warnings", []))
        if (age is None or age > LINK_CHECK_STALE_DAYS) and "link_check_needed" not in warnings:
            warnings.append("link_check_needed")
        validated.append({**item, "warnings": warnings})
    summary: ListingCheckSummary = {"database_match_count": len(ranked)}
    return {"ranked_listings": validated, "summary": summary}


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


def ranking_weights(preferences: SearchPreferences) -> dict[str, float]:
    """Without stated priorities, each ranking factor's share, for a listing with data for all."""
    names = _ranking_factors(preferences)
    return {name: round(1 / len(names), 2) for name in names}


def ranking_order(preferences: SearchPreferences) -> list[str]:
    """What stated priorities compare, in order, ending with rent; empty without any."""
    order = [_PRIORITY_FACTOR.get(name, name) for name in preferences.ranking_priority]
    return [*order, *([] if "price" in order else ["price"])] if order else []


def ranking_value(name: str, listing: Listing, preferences: SearchPreferences) -> float | None:
    """What a stated priority compares, smaller first; None when the listing does not state it."""
    if name == "price":
        return listing.get("rent_monthly_sgd")
    if name == "mrt":
        return mrt_minutes(listing)
    if name == "commute":
        trips = []
        if preferences.faculty is not None or preferences.other_destination is None:
            trips.append(commute_minutes(listing, preferences))
        if preferences.other_destination is not None:
            trips.append(other_commute_minutes(listing, preferences))
        return None if None in trips else max(trips)
    if name == "food":
        return listing.get(_FOOD_RANK)
    if name == "school_distance":
        return listing.get("pg_school_nearest_walk_min")
    more = rental_area_sqm(listing) if name == "space" else listing.get(AMENITY_FIELDS[name])
    return None if more is None else -more


def _priority_key(listing: Listing, preferences: SearchPreferences, order: list[str]) -> tuple:
    values = (ranking_value(name, listing, preferences) for name in order)
    return (*((value is None, value or 0) for value in values), listing["listing_id"])


def _ranking_factors(preferences: SearchPreferences) -> list[str]:
    priorities = preferences.ranking_priority
    asked = {
        "mrt": True,
        "commute": preferences.max_commute_minutes is not None or preferences.max_other_commute_minutes is not None or "commute" in priorities,
        "food": "amenities" in priorities,
        "space": "space" in priorities,
        "price": preferences.max_price_sgd is not None,
    }
    asked.update({name: name in priorities for name in (*AMENITY_FIELDS, "school_distance")})
    return [name for name in _RANKING_CRITERIA if asked[name]]


def _mrt_reference_m(preferences: SearchPreferences) -> float:
    minutes = preferences.max_mrt_minutes
    reference = max(minutes if minutes is not None else _SOFT_MRT_REFERENCE_MINUTES, 1) * _METRES_PER_MINUTE
    if preferences.max_mrt_distance_m is not None:
        reference = min(reference, preferences.max_mrt_distance_m) if minutes is not None else preferences.max_mrt_distance_m
    return max(reference, 1)


def _commute_reference(preferences: SearchPreferences) -> int:
    return max(preferences.max_commute_minutes or _SOFT_COMMUTE_REFERENCE_MINUTES, 1)


def _commute_ratio(listing: Listing, preferences: SearchPreferences) -> float | None:
    """The longer trip, each over its own limit (45 minutes without one): to the user's faculty and
    to the other destination, whichever there are. A trip without data counts as its limit, 1."""
    parts = []
    if preferences.faculty is not None or preferences.other_destination is None:
        parts.append(_ratio(commute_minutes(listing, preferences), _commute_reference(preferences)))
    if preferences.other_destination is not None:
        limit = max(preferences.max_other_commute_minutes or _SOFT_COMMUTE_REFERENCE_MINUTES, 1)
        parts.append(_ratio(other_commute_minutes(listing, preferences), limit))
    if all(part is None for part in parts):
        return None
    return max(1.0 if part is None else part for part in parts)


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
