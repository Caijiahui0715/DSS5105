"""Decision logic on top of tools.py.

Strict matches stay identical to search_listings(). Listings that fail only
because the data does not state a requested condition are reported as
needs-confirmation instead of disappearing, and each condition can be
diagnosed by dropping it on its own.
"""

import json
import math
import sqlite3
from collections import Counter
from functools import cache
from pathlib import Path

from models import Listing, SearchPreferences
from tools import (
    EXTRA_CONDITION_LABELS,
    AMENITY_FIELDS,
    _SOFT_MRT_REFERENCE_MINUTES,
    FURNISHED,
    TENANT_GENDER_ACCEPTS,
    _enum,
    extra_condition_status,
    mrt_distance_m,
    mrt_minutes,
    rank_listings,
    rental_area_sqm,
    resolve_search_location,
    search_listings,
)


EVIDENCE_PATH = Path(__file__).parent / "output-final-delivery" / "source_evidence_v1.json"

# A condition is active when its preference differs from this neutral value.
_NEUTRAL = {
    "max_price_sgd": None,
    "district_code": None,
    "room_type": None,
    "rental_scope": None,
    "property_types": None,
    "max_mrt_minutes": None,
    "min_bedrooms": None,
    "min_area_sqm": None,
    "occupant_count": None,
    "cooking_required": False,
    "tenant_gender": None,
    "landlord_not_living_in": False,
    "furnished_required": False,
    "air_conditioning_required": False,
    "max_commute_minutes": None,
}
# Rent and district are required V1 fields; these conditions can be unstated.
_SPARSE = (
    "room_type",
    "rental_scope",
    "max_mrt_minutes",
    "min_bedrooms",
    "min_area_sqm",
    "occupant_count",
    "cooking_required",
    "tenant_gender",
    "landlord_not_living_in",
    "furnished_required",
    "air_conditioning_required",
    "max_commute_minutes",
)
# A stated ranking priority also needs data; without it a listing cannot be ranked on it.
_PRIORITY_DATA = {
    "amenities": ("nearby_food", lambda listing: listing.get("food_rank")),
    "mrt": ("max_mrt_minutes", mrt_distance_m),
    "commute": ("max_commute_minutes", lambda listing: listing.get("commute_nus_minutes")),
    "space": ("min_area_sqm", rental_area_sqm),
}
_NEUTRAL.update({field: SearchPreferences.model_fields[field].default for field in EXTRA_CONDITION_LABELS})
_SPARSE += tuple(EXTRA_CONDITION_LABELS)
_PRIORITY_DATA.update({name: (name, lambda listing, name=name: listing.get(f"{name}_rank")) for name in AMENITY_FIELDS})
_PRIORITY_DATA["school_distance"] = ("max_school_walk_minutes", lambda listing: listing.get("pg_school_nearest_walk_min"))
_EVIDENCE_FIELDS = (
    "headline",
    "card_text",
    "availability_text",
    "tenant_label_text",
    "rule_evidence",
    "source_url",
)


def active_conditions(preferences: SearchPreferences) -> list[str]:
    return [
        field
        for field, neutral in _NEUTRAL.items()
        if getattr(preferences, field) != neutral
    ]


def condition_status(
    field: str,
    listing: Listing,
    preferences: SearchPreferences,
) -> str:
    """Return pass, fail or unknown; pass uses the same rule as the SQL filter."""
    wanted = getattr(preferences, field)
    if field in EXTRA_CONDITION_LABELS:
        return extra_condition_status(field, listing, preferences)
    if field == "max_price_sgd":
        return _check(listing.get("rent_monthly_sgd"), lambda rent: rent <= wanted)
    if field == "district_code":
        return _check(
            listing.get("district_code"),
            lambda code: code.casefold() == wanted.strip().casefold(),
        )
    if field == "room_type":
        room = listing.get("room_type")
        if room == _enum(wanted):
            return "pass"
        # An unstated type is possible only if the scope fits: a studio is a whole unit.
        scope = "entire_unit" if _enum(wanted) == "studio" else "room"
        unstated = room in {None, "unknown", "room_unspecified"}
        fits = listing.get("rental_scope") in {None, "unknown", scope}
        return "unknown" if unstated and fits else "fail"
    if field == "property_types":
        return _check(listing.get("property_type"), lambda value: value in wanted)
    if field == "rental_scope":
        scope = listing.get("rental_scope")
        return _check(None if scope == "unknown" else scope, lambda value: value == wanted)
    if field == "max_mrt_minutes":
        return _check(mrt_minutes(listing), lambda minutes: minutes <= wanted)
    if field == "min_bedrooms":
        if listing.get("rental_scope") == "room":
            return "fail"
        return _check(listing.get("bedrooms"), lambda bedrooms: bedrooms >= wanted)
    if field == "occupant_count":
        return _check(listing.get("tenant_count_reported"), lambda count: count >= wanted)
    if field == "min_area_sqm":
        return _check(rental_area_sqm(listing), lambda area: area >= wanted)
    if field == "cooking_required":
        return _stated(listing.get("cooking_policy"), lambda value: value in {"allowed", "light_only"})
    if field == "tenant_gender":
        return _stated(listing.get("gender_restriction"), lambda value: value in TENANT_GENDER_ACCEPTS[wanted])
    if field == "landlord_not_living_in":
        return _stated(listing.get("landlord_lives_in"), lambda value: value == "no")
    if field == "furnished_required":
        return _stated(listing.get("furnishing"), lambda value: value in FURNISHED)
    if field == "air_conditioning_required":
        return _stated(listing.get("air_conditioning"), lambda value: value == "yes")
    if field == "max_commute_minutes":
        return _check(listing.get("commute_nus_minutes"), lambda minutes: minutes <= wanted)
    raise ValueError(f"unsupported condition: {field}")


def search_with_unknowns(
    connection: sqlite3.Connection,
    preferences: SearchPreferences,
    excluded_listing_ids: list[str] | None = None,
) -> tuple[list[Listing], list[Listing]]:
    """Split candidates into strict matches and listings blocked only by unstated data."""
    preferences = resolve_search_location(preferences)
    # SQL keeps only listings stating every sparse condition and each priority's data; drop those
    # filters here and sort listings by each condition's status instead.
    base = preferences.model_copy(
        update={**{field: _NEUTRAL[field] for field in _SPARSE}, "ranking_priority": ()}
    )
    active = [field for field in active_conditions(preferences) if field in _SPARSE]
    strict, needs_confirmation = [], []
    for listing in search_listings(connection, base, excluded_listing_ids):
        statuses = {field: condition_status(field, listing, preferences) for field in active}
        if "fail" in statuses.values():
            continue
        unknown = [field for field, status in statuses.items() if status == "unknown"]
        unknown += [label for label in _unranked_priority(listing, preferences) if label not in unknown]
        if unknown:
            needs_confirmation.append({**listing, "unknown_conditions": unknown})
        else:
            strict.append(listing)
    return strict, needs_confirmation


def _unranked_priority(listing: Listing, preferences: SearchPreferences) -> list[str]:
    """Name each stated ranking priority this listing has no data for."""
    checks = [_PRIORITY_DATA[name] for name in preferences.ranking_priority if name in _PRIORITY_DATA]
    return [label for label, data in checks if data(listing) is None]


def diagnose_conditions(
    connection: sqlite3.Connection,
    preferences: SearchPreferences,
    excluded_listing_ids: list[str] | None = None,
) -> list[dict]:
    """For each active condition, report what dropping only that condition yields.

    Counts are database matches before URL checks. known_fail and unknown split
    the listings that meet every other condition by their status on this one.
    """
    preferences = resolve_search_location(preferences)
    rows = []
    for field in active_conditions(preferences):
        others = preferences.model_copy(update={field: _NEUTRAL[field]})
        candidates, _ = search_with_unknowns(connection, others, excluded_listing_ids)
        statuses = Counter(
            condition_status(field, listing, preferences) for listing in candidates
        )
        row = {
            "condition": field,
            "value": getattr(preferences, field),
            "database_matches_without_it": len(candidates),
            "known_fail": statuses["fail"],
            "unknown": statuses["unknown"],
        }
        limit_of = {"max_price_sgd": lambda listing: listing["rent_monthly_sgd"], "max_mrt_minutes": mrt_minutes}
        if field in limit_of:
            values = [value for value in map(limit_of[field], candidates) if value is not None]
            row["smallest_limit_with_a_match"] = whole(min(values)) if values else None
        rows.append(row)
    return rows


def rental_scope_mix(
    preferences: SearchPreferences,
    strict: list[Listing],
    shown: list[Listing],
) -> dict | None:
    """When the user has not chosen a whole unit or a room and strict matches include both,
    say which kind is shown and what the other kind offers (database counts)."""
    if preferences.rental_scope or preferences.room_type or not shown:
        return None
    groups = {
        scope: [listing["rent_monthly_sgd"] for listing in strict if listing.get("rental_scope") == scope]
        for scope in ("entire_unit", "room")
    }
    if not all(groups.values()):
        return None
    return {
        "shown_scopes": sorted({listing.get("rental_scope") for listing in shown} & set(groups)),
        **{
            scope: {"database_count": len(rents), "cheapest_sgd": whole(min(rents))}
            for scope, rents in groups.items()
        },
    }


def default_budget_levels(budget: int) -> list[int]:
    """About 1.15x, 1.5x and 2.3x the budget, rounded up to the next S$100."""
    return sorted({math.ceil(budget * factor / 100) * 100 for factor in (1.15, 1.5, 2.3)})


def budget_ladder(
    connection: sqlite3.Connection,
    preferences: SearchPreferences,
    budgets: list[int | None],
    excluded_listing_ids: list[str] | None = None,
) -> list[dict]:
    """Database counts at each budget (None means no limit) with every other condition kept."""
    rows = []
    for budget in budgets:
        strict, pending = search_with_unknowns(
            connection,
            preferences.model_copy(update={"max_price_sgd": budget}),
            excluded_listing_ids,
        )
        rows.append(
            {
                "max_price_sgd": budget,
                "strict_matches": _profile(strict),
                "needs_confirmation": _profile(pending),
            }
        )
    return rows


def explain_listing(
    listing: Listing,
    preferences: SearchPreferences,
    evidence: dict | None = None,
) -> dict:
    """Ranking factors, per-condition status and the source of each fact."""
    ranked = rank_listings([listing], preferences)[0]
    walk_minutes = listing.get("mrt_walk_minutes")
    return {
        "listing_id": listing["listing_id"],
        "rank_value": ranked["rank_value"],
        "rank_value_lower_is_better": True,
        "factors": ranked["factors"],
        "factor_formulas": {
            "price": "rent_monthly_sgd / max_price_sgd",
            "mrt": "walking metres to an operating MRT station / max_mrt_distance_m or max_mrt_minutes x 85 m (the smaller if both, 850 m without either); no data or an unopened station counts as 1",
            "commute": "public-transport minutes to NUS / max_commute_minutes (45 without a limit); no data counts as 1",
            "food": "position among all listings on nearby F&B and hawker centres within 1 km (0 is the most choice)",
            "space": "descending area percentile within the same rental_scope and area_scope (0 is largest); unstated rental area counts as 0.5",
            **{name: f"descending position among all listings with {field} data (lower means more choice)" for name, field in AMENITY_FIELDS.items()},
            "school_distance": "nearest-school walking minutes / max_school_walk_minutes (10 without a limit)",
        },
        "conditions": {
            field: condition_status(field, listing, preferences)
            for field in active_conditions(preferences)
        },
        "rent_monthly_sgd": whole(listing.get("rent_monthly_sgd")),
        "rent_monthly_sgd_card": whole(listing.get("rent_monthly_sgd_card")),
        "area_sqm": listing.get("area_sqm"),
        "area_scope": listing.get("area_scope"),
        "nearby_1km": {
            key: listing[field]
            for key, field in (("fnb", "poi_fnb_1km"), ("hawker_centres", "poi_hawker_1km"), ("libraries", "poi_library_1km"), ("sports", "poi_sport_1km"), ("healthcare", "poi_healthcare_1km"), ("community", "poi_community_1km"))
            if listing.get(field) is not None
        },
        "mrt_minutes": mrt_minutes(listing),
        "mrt_distance_m": whole(mrt_distance_m(listing)),
        "commute_nus_minutes": whole(listing.get("commute_nus_minutes")),
        "sources": {
            "rent_monthly_sgd": (
                "rechecked_listing"
                if listing.get("rent_monthly_sgd_now") is not None
                else "listing_card"
            ),
            "mrt_minutes": (
                None
                if mrt_minutes(listing) is None
                else "onemap_walking_route"
                if walk_minutes is not None
                else "listing_card"
            ),
            "commute_nus_minutes": (
                "onemap_public_transport_route" if listing.get("commute_nus_minutes") is not None else None
            ),
        },
        "collected_at": listing.get("collected_at"),
        "listing_url": listing.get("listing_url"),
        "evidence": evidence,
    }


@cache
def load_source_evidence(path: Path = EVIDENCE_PATH) -> dict[str, dict]:
    """Source quotes by listing_id; an absent file simply means no quotes."""
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    return {
        str(record["listing_id"]): {
            field: record[field] for field in _EVIDENCE_FIELDS if record.get(field)
        }
        for record in records
    }


def whole(value):
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _profile(listings: list[Listing]) -> dict:
    whole_unit_rents = [
        listing["rent_monthly_sgd"]
        for listing in listings
        if listing.get("rental_scope") == "entire_unit"
    ]
    near_mrt = [
        minutes
        for minutes in map(mrt_minutes, listings)
        if minutes is not None and minutes <= _SOFT_MRT_REFERENCE_MINUTES
    ]
    return {
        "count": len(listings),
        "mrt_within_10_min": len(near_mrt),
        "entire_unit": len(whole_unit_rents),
        "cheapest_entire_unit_sgd": whole(min(whole_unit_rents)) if whole_unit_rents else None,
    }


def _check(value, test) -> str:
    return "unknown" if value is None else "pass" if test(value) else "fail"


def _stated(value, test) -> str:
    """Like _check for text labels, where "unknown" also means the data does not say."""
    return _check(None if value == "unknown" else value, test)
