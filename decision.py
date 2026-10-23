"""Decision logic on top of tools.py.

Strict matches stay identical to search_listings(). Listings that fail only
because the data does not state a requested condition are reported as
needs-confirmation instead of disappearing, and each condition can be
diagnosed by dropping it on its own.
"""

import json
import math
from collections import Counter
from functools import cache
from pathlib import Path

from group_db import Database
from models import Listing, SearchPreferences
from tools import (
    EXTRA_CONDITION_LABELS,
    AMENITY_FIELDS,
    _SOFT_MRT_REFERENCE_MINUTES,
    FURNISHED,
    MAX_LEGAL_OCCUPANTS,
    TENANT_GENDER_ACCEPTS,
    _enum,
    commute,
    commute_minutes,
    destination_trip,
    destination_view,
    extra_condition_status,
    mrt_distance_m,
    mrt_minutes,
    other_commute_minutes,
    own_commute_needed,
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
    "amenities": ("nearby_food", lambda listing, preferences: listing.get("food_rank")),
    "mrt": ("max_mrt_minutes", lambda listing, preferences: mrt_distance_m(listing)),
    "commute": ("max_commute_minutes", commute_minutes),
    "space": ("min_area_sqm", lambda listing, preferences: rental_area_sqm(listing)),
}
_NEUTRAL.update({field: SearchPreferences.model_fields[field].default for field in EXTRA_CONDITION_LABELS})
_SPARSE += tuple(EXTRA_CONDITION_LABELS)
_PRIORITY_DATA.update({name: (name, lambda listing, preferences, name=name: listing.get(f"{name}_rank")) for name in AMENITY_FIELDS})
_PRIORITY_DATA["school_distance"] = ("max_school_walk_minutes", lambda listing, preferences: listing.get("pg_school_nearest_walk_min"))
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
        scope = listing.get("rental_scope")
        if scope == "entire_unit":
            return "pass" if wanted <= MAX_LEGAL_OCCUPANTS else "unknown"
        if scope != "room":
            return "unknown"
        # A room's "N pax" label may count the whole flat, so it can only rule out sharing.
        return "pass" if wanted == 1 else "fail" if listing.get("tenant_count_reported") == 1 else "unknown"
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
        return _check(commute_minutes(listing, preferences), lambda minutes: minutes <= wanted)
    raise ValueError(f"unsupported condition: {field}")


def search_with_unknowns(
    connection: Database,
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
    """Name each stated ranking priority this listing has no data for; ranking by commute needs the
    trip to each destination there is."""
    checks = [_PRIORITY_DATA[name] for name in preferences.ranking_priority if name in _PRIORITY_DATA and name != "commute"]
    if "commute" in preferences.ranking_priority:
        if own_commute_needed(preferences):
            checks.append(_PRIORITY_DATA["commute"])
        if preferences.other_destination is not None:
            checks.append(("max_other_commute_minutes", other_commute_minutes))
    return [label for label, data in checks if data(listing, preferences) is None]


def route_candidates(
    connection: Database,
    preferences: SearchPreferences,
    excluded_listing_ids: list[str] | None = None,
) -> list[Listing]:
    """The listings a search with these preferences may show, ask to confirm or suggest relaxing to:
    those not known to fail a condition, leaving out the commute limits and the conditions a
    relaxation suggests changing (MRT, lease), with the budget 10% higher as a relaxation suggests.
    Routes to the other destination are worked out for these (place_routes.py)."""
    budget = preferences.max_price_sgd
    base = preferences.model_copy(
        update={
            "max_commute_minutes": None,
            "max_other_commute_minutes": None,
            "max_mrt_minutes": None,
            "lease_months": None,
            "ranking_priority": (),
            "max_price_sgd": None if budget is None else (budget * 11 + 9) // 10,
        }
    )
    strict, pending = search_with_unknowns(connection, base, excluded_listing_ids)
    return strict + pending


def diagnose_conditions(
    connection: Database,
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
        limit_of = {
            "max_price_sgd": lambda listing: listing["rent_monthly_sgd"],
            "max_mrt_minutes": mrt_minutes,
            "max_commute_minutes": lambda listing: commute_minutes(listing, preferences),
            "max_other_commute_minutes": lambda listing: other_commute_minutes(listing, preferences),
        }
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
    connection: Database,
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
            "commute": "minutes to the user's faculty (public transport leaving 08:30 on a weekday, or walking within 1.5 km when faster) / max_commute_minutes (45 without a limit); with other_destination, the larger of that and minutes to it / max_other_commute_minutes (45 without a limit); no data counts as 1",
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
        "faculty": preferences.faculty,
        "commute_minutes": whole(commute_minutes(listing, preferences)),
        "commute_mode": (commute(listing, preferences.faculty) or {}).get("mode"),
        "other_destination": destination_view(preferences.other_destination),
        "other_commute_minutes": whole(other_commute_minutes(listing, preferences)),
        "other_commute_mode": (destination_trip(listing, preferences.other_destination) or {}).get("mode"),
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
            "commute_minutes": {
                "transit": "onemap_public_transport_route",
                "walk": "onemap_walking_route",
                "transit_google": "google_public_transport_route",
            }.get((commute(listing, preferences.faculty) or {}).get("mode")),
            "other_commute_minutes": _ROUTE_SOURCES.get((destination_trip(listing, preferences.other_destination) or {}).get("mode")),
        },
        "collected_at": listing.get("collected_at"),
        "listing_url": listing.get("listing_url"),
        "evidence": evidence,
    }


_ROUTE_SOURCES = {
    "transit": "onemap_public_transport_route",
    "walk": "onemap_walking_route",
    "transit_google": "google_public_transport_route",
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
