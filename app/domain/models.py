"""UI-facing domain objects. Source facts and demo enrichment stay separate."""
from dataclasses import dataclass, field
from typing import Any, Literal

Provenance = Literal['source', 'derived', 'mock', 'unavailable']
Status = Literal['pass', 'needs_confirmation', 'fail']

@dataclass(frozen=True)
class Listing:
    id: str
    facts: dict[str, Any]
    metadata: dict[str, Any]
    evidence: dict[str, Any]
    images: tuple[str, ...]
    provenance: dict[str, Provenance]
    source_fields: dict[str, Any] = field(default_factory=dict)

@dataclass
class RentalRequirements:
    max_budget: float | None = 2500
    rental_scope: str | None = 'room'
    min_bedrooms: int | None = None

@dataclass
class RentalPreferences:
    districts: list[str] = field(default_factory=lambda: ['D05'])
    mrt_distance: int | None = 1000
    commute_minutes: int | None = 40
    furnishing: str = 'No preference'
    private_bathroom: str = 'No preference'
    cooking: str = 'No preference'
    air_conditioning: str = 'No preference'
    pets: str = 'No preference'
    property_type: str = 'No preference'

@dataclass
class ConstraintEvaluation:
    status: Status
    checks: dict[str, dict[str, str]]

@dataclass
class Recommendation:
    listing_id: str
    rank: int
    # The agent ranks without a 0-100 score; only the offline demo has one.
    score: int | None
    match_level: str
    evaluation: ConstraintEvaluation
    reasons: list[str]
    tradeoffs: list[str]
    unknown_factors: list[str]
    breakdown: dict[str, float | None]
    is_demo_score: bool = True
    # The agent's facts for this listing (commute, MRT, link check), as the backend sent them.
    facts: dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentResponse:
    text: str
    requirements: RentalRequirements
    preferences: RentalPreferences
    # None when the turn did not search, so the listing panel keeps the earlier results.
    recommendations: list[Recommendation] | None
    clarification: str | None = None
    # From the agent backend: how the reply was made, the conversation's shortlist, and
    # whether the listings are only a preview that left the saved criteria unchanged.
    steps: list[str] = field(default_factory=list)
    shortlist: list[str] | None = None
    preview: bool = False

class ApiError(RuntimeError):
    """A safe, user-displayable adapter failure."""
