from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Listing = dict[str, Any]
RestrictionSummary = dict[str, str]
RankingResult = dict[str, Any]
RelaxationSuggestion = dict[str, Any]
UserIntent = Literal[
    "search",
    "accept_relaxation",
    "reject_relaxation",
    "show_results",
    "unknown",
]


class SearchPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_price_sgd: int | None = Field(
        default=None,
        gt=0,
        description="Maximum monthly rent in SGD; null when not explicitly stated.",
    )
    room_type: str | None = Field(
        default=None,
        description="Requested room type, such as Common Room or Master Room.",
    )
    district_code: str | None = Field(
        default=None,
        description="Singapore district code such as D05; null when absent.",
    )
    max_mrt_minutes: int | None = Field(
        default=None,
        ge=0,
        description="Maximum reported walking minutes to MRT; null when absent.",
    )
    verified_only: bool = Field(
        default=False,
        description="True only when the user explicitly requires verified listings.",
    )
    ranking_priority: Literal["balanced", "price", "mrt"] = Field(
        default="balanced",
        description="Explicit soft preference: balanced, lower price, or nearer MRT.",
    )


class ParsedTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: UserIntent
    preferences: SearchPreferences
    relaxation_number: int | None = Field(
        default=None,
        ge=1,
        description="One-based pending relaxation number when accepting or previewing one.",
    )
