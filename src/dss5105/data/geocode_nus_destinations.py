from pathlib import Path
import csv
import os

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "nus_destinations_seed.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "nus_destinations_geocoded.csv"
)


ONEMAP_SEARCH_URL = (
    "https://www.onemap.gov.sg/api/common/elastic/search"
)


def geocode_postcode(
    postcode: str,
    token: str,
) -> dict | None:
    """
    Use OneMap Search API to convert a Singapore postcode
    into latitude / longitude.
    """

    params = {
        "searchVal": postcode,
        "returnGeom": "Y",
        "getAddrDetails": "Y",
        "pageNum": 1,
    }

    headers = {
        "Authorization": token,
    }

    response = requests.get(
        ONEMAP_SEARCH_URL,
        params=params,
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            f"OneMap API error: {data['error']}"
        )

    results = data.get("results", [])

    if not results:
        return None

    first = results[0]

    return {
        "latitude": first.get("LATITUDE"),
        "longitude": first.get("LONGITUDE"),
        "onemap_address": first.get("ADDRESS"),
    }


def main():
    load_dotenv()

    token = os.getenv("ONEMAP_TOKEN")

    if not token:
        raise RuntimeError(
            "ONEMAP_TOKEN is missing from .env"
        )

    with INPUT_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    successful = 0
    failed = 0

    for row in rows:
        postcode = row["postal_code"].strip()

        print(
            f"Geocoding "
            f"{row['faculty_code']} "
            f"({postcode})..."
        )

        result = geocode_postcode(
            postcode,
            token,
        )

        if result is None:
            print("  No result found.")

            row["latitude"] = ""
            row["longitude"] = ""
            row["onemap_address"] = ""

            failed += 1

            continue

        row["latitude"] = result["latitude"]
        row["longitude"] = result["longitude"]
        row["onemap_address"] = (
            result["onemap_address"]
        )

        successful += 1

        print(
            f"  {row['latitude']}, "
            f"{row['longitude']}"
        )

    fieldnames = list(rows[0].keys())

    if "onemap_address" not in fieldnames:
        fieldnames.append(
            "onemap_address"
        )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()
        writer.writerows(rows)

    print()
    print("=== Geocoding Summary ===")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()