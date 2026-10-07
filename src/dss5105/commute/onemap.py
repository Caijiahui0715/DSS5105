from datetime import datetime
import os
from typing import Any

import requests
from dotenv import load_dotenv


ONEMAP_ROUTE_URL = (
    "https://www.onemap.gov.sg/api/public/routingsvc/route"
)


def get_onemap_token() -> str:
    """
    Read OneMap API token from .env.
    """

    load_dotenv()

    token = os.getenv("ONEMAP_TOKEN")

    if not token:
        raise RuntimeError(
            "ONEMAP_TOKEN is missing from .env"
        )

    return token


def get_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    *,
    route_type: str = "pt",
    mode: str = "TRANSIT",
    date: str | None = None,
    time: str | None = None,
    max_walk_distance: int = 1000,
    num_itineraries: int = 1,
) -> dict[str, Any]:
    """
    Request a route from OneMap.

    Public transport requires:
    - route_type = "pt"
    - date
    - time
    - mode
    """

    token = get_onemap_token()

    now = datetime.now()

    if date is None:
        date = now.strftime("%m-%d-%Y")

    if time is None:
        time = now.strftime("%H:%M:%S")

    params = {
        "start": f"{start_lat},{start_lon}",
        "end": f"{end_lat},{end_lon}",
        "routeType": route_type,
    }

    if route_type == "pt":
        params.update(
            {
                "date": date,
                "time": time,
                "mode": mode,
                "maxWalkDistance": max_walk_distance,
                "numItineraries": num_itineraries,
            }
        )

    headers = {
        "Authorization": token,
    }

    response = requests.get(
        ONEMAP_ROUTE_URL,
        params=params,
        headers=headers,
        timeout=30,
    )

    if not response.ok:
        raise RuntimeError(
            f"OneMap routing failed "
            f"({response.status_code}): "
            f"{response.text}"
        )

    return response.json()


def extract_route_summary(
    route_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract distance and duration from either:
    - public transport response
    - walk / drive / cycle response
    """

    # Public transport
    plan = route_data.get("plan")

    if plan:
        itineraries = plan.get(
            "itineraries",
            [],
        )

        if itineraries:
            best_route = itineraries[0]

            duration_seconds = best_route.get(
                "duration"
            )

            legs = best_route.get(
                "legs",
                [],
            )

            distance_m = sum(
                float(leg.get("distance", 0))
                for leg in legs
            )

            duration_min = None

            if duration_seconds is not None:
                duration_min = round(
                    float(duration_seconds) / 60,
                    2,
                )

            return {
                "distance_m": round(distance_m),
                "duration_min": duration_min,
            }

    # Walk / drive / cycle
    summary = route_data.get(
        "route_summary"
    )

    if summary:
        total_distance = summary.get(
            "total_distance"
        )

        total_time = summary.get(
            "total_time"
        )

        duration_min = None

        if total_time is not None:
            duration_min = round(
                float(total_time) / 60,
                2,
            )

        return {
            "distance_m": (
                int(total_distance)
                if total_distance is not None
                else None
            ),
            "duration_min": duration_min,
        }

    return {
        "distance_m": None,
        "duration_min": None,
    }