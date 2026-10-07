from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from dss5105.backend.recommendation_service import (
    recommend_listings,
)
from dss5105.database.connection import (
    get_connection,
)


app = FastAPI(
    title="Singapore Rental Decision Agent API",
    description=(
        "Backend API for retrieving and ranking "
        "Singapore rental listings for NUS users."
    ),
    version="0.1.0",
)


# ---------------------------------------------------------
# Development CORS settings
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Request schemas
# ---------------------------------------------------------

class RecommendationRequest(BaseModel):
    """
    User requirements and soft preferences
    used by the recommendation engine.
    """

    faculty_code: str = Field(
        ...,
        examples=["SOC"],
    )

    max_budget: float | None = Field(
        default=None,
        gt=0,
        examples=[2000],
    )

    rental_scope: str | None = Field(
        default=None,
        examples=["room"],
    )

    min_bedrooms: int | None = Field(
        default=None,
        ge=0,
        examples=[1],
    )

    preferred_furnishing: str | None = Field(
        default=None,
        examples=["fully_furnished"],
    )

    preferred_property_type: str | None = Field(
        default=None,
        examples=["hdb_flat"],
    )

    limit: int = Field(
        default=10,
        ge=1,
        le=50,
    )


# ---------------------------------------------------------
# Basic endpoints
# ---------------------------------------------------------

@app.get("/")
def root() -> dict[str, str]:
    """
    Basic API information.
    """

    return {
        "service": (
            "Singapore Rental Decision Agent API"
        ),
        "status": "running",
    }


@app.get("/health")
def health_check() -> dict[str, Any]:
    """
    Verify that the API and PostgreSQL database
    are both reachable.
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:

                cur.execute(
                    "SELECT 1;"
                )

                result = cur.fetchone()

    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Database unavailable: {exc}"
            ),
        )

    return {
        "status": "ok",
        "database": (
            "connected"
            if result
            else "unknown"
        ),
    }


# ---------------------------------------------------------
# NUS destinations
# ---------------------------------------------------------

@app.get("/destinations")
def get_destinations() -> list[dict[str, Any]]:
    """
    Return all available NUS faculty/school
    representative destinations.
    """

    query = """
        SELECT
            destination_id,
            faculty_code,
            faculty_name,
            destination_name,
            address,
            postal_code,
            campus_area,
            latitude,
            longitude
        FROM nus_destinations
        WHERE is_default = TRUE
        ORDER BY faculty_code;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(query)

            rows = cur.fetchall()

            columns = [
                desc.name
                for desc in cur.description
            ]

    return [
        dict(zip(columns, row))
        for row in rows
    ]


# ---------------------------------------------------------
# Recommendations
# ---------------------------------------------------------

@app.post("/recommendations")
def create_recommendations(
    request: RecommendationRequest,
) -> dict[str, Any]:
    """
    Generate personalised rental recommendations.

    Pipeline:
    active listings
        -> hard constraints
        -> cached NUS commute
        -> suitability scoring
        -> ranked recommendations
    """

    try:
        recommendations = recommend_listings(
            faculty_code=(
                request.faculty_code.upper()
            ),
            max_budget=request.max_budget,
            rental_scope=request.rental_scope,
            min_bedrooms=request.min_bedrooms,
            preferred_furnishing=(
                request.preferred_furnishing
            ),
            preferred_property_type=(
                request.preferred_property_type
            ),
            limit=request.limit,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Recommendation engine failed: "
                f"{exc}"
            ),
        )

    return {
        "faculty_code": (
            request.faculty_code.upper()
        ),

        "request": {
            "max_budget": (
                request.max_budget
            ),
            "rental_scope": (
                request.rental_scope
            ),
            "min_bedrooms": (
                request.min_bedrooms
            ),
            "preferred_furnishing": (
                request.preferred_furnishing
            ),
            "preferred_property_type": (
                request.preferred_property_type
            ),
        },

        "count": len(
            recommendations
        ),

        "recommendations": (
            recommendations
        ),
    }