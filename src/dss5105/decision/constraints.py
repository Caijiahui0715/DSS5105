from typing import Any


PASS = "pass"
FAIL = "fail"
NEEDS_CONFIRMATION = "needs_confirmation"


def evaluate_max_budget(
    rent_monthly_sgd: Any,
    max_budget: float,
) -> dict:
    if rent_monthly_sgd is None:
        return {
            "status": NEEDS_CONFIRMATION,
            "reason": "Monthly rent is not available.",
        }

    if float(rent_monthly_sgd) <= max_budget:
        return {
            "status": PASS,
            "reason": f"Monthly rent is within the SGD {max_budget:.0f} budget.",
        }

    return {
        "status": FAIL,
        "reason": f"Monthly rent exceeds the SGD {max_budget:.0f} budget.",
    }


def evaluate_rental_scope(
    rental_scope: str | None,
    required_scope: str,
) -> dict:
    if rental_scope is None or rental_scope == "unknown":
        return {
            "status": NEEDS_CONFIRMATION,
            "reason": "Rental scope is not confirmed.",
        }

    if rental_scope == required_scope:
        return {
            "status": PASS,
            "reason": f"Rental scope matches '{required_scope}'.",
        }

    return {
        "status": FAIL,
        "reason": (
            f"Rental scope is '{rental_scope}', "
            f"not '{required_scope}'."
        ),
    }


def evaluate_min_bedrooms(
    bedrooms: int | None,
    min_bedrooms: int,
) -> dict:
    if bedrooms is None:
        return {
            "status": NEEDS_CONFIRMATION,
            "reason": "Bedroom count is not confirmed.",
        }

    if bedrooms >= min_bedrooms:
        return {
            "status": PASS,
            "reason": (
                f"Listing has {bedrooms} bedroom(s), "
                f"meeting the minimum of {min_bedrooms}."
            ),
        }

    return {
        "status": FAIL,
        "reason": (
            f"Listing has {bedrooms} bedroom(s), "
            f"below the minimum of {min_bedrooms}."
        ),
    }


def evaluate_hard_constraints(
    listing: dict,
    *,
    max_budget: float | None = None,
    rental_scope: str | None = None,
    min_bedrooms: int | None = None,
) -> dict:
    checks = {}

    if max_budget is not None:
        checks["max_budget"] = evaluate_max_budget(
            listing.get("rent_monthly_sgd"),
            max_budget,
        )

    if rental_scope is not None:
        checks["rental_scope"] = evaluate_rental_scope(
            listing.get("rental_scope"),
            rental_scope,
        )

    if min_bedrooms is not None:
        checks["min_bedrooms"] = evaluate_min_bedrooms(
            listing.get("bedrooms"),
            min_bedrooms,
        )

    statuses = [check["status"] for check in checks.values()]

    if FAIL in statuses:
        overall_status = FAIL
    elif NEEDS_CONFIRMATION in statuses:
        overall_status = NEEDS_CONFIRMATION
    else:
        overall_status = PASS

    return {
        "listing_id": listing.get("listing_id"),
        "status": overall_status,
        "checks": checks,
    }