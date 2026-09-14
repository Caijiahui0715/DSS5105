from datetime import date
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
    "reject_results",
    "remove_shortlisted_listing",
    "show_shortlist",
    "shortlist_listing",
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
    room_type_flexible: bool = Field(
        default=False,
        description="True when the user explicitly accepts any room type.",
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
    move_in_date: date | None = Field(
        default=None,
        description="Desired move-in date; null when not stated or flexible.",
    )
    move_in_flexible: bool = Field(
        default=False,
        description="True when the user explicitly says the move-in date is flexible.",
    )
    cooking_required: bool = Field(
        default=False,
        description="True only when the listing must allow at least limited cooking.",
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
    reject_all_shown: bool = Field(
        default=False,
        description="True when the user rejects every listing shown in the previous reply.",
    )
    rejected_listing_numbers: list[int] = Field(
        default_factory=list,
        description="One-based displayed listing numbers explicitly rejected by the user.",
    )
    shortlist_listing_numbers: list[int] = Field(
        default_factory=list,
        description="One-based displayed listing numbers to add to the shortlist.",
    )
    shortlist_listing_ids: list[str] = Field(
        default_factory=list,
        description="Explicit listing IDs to add to the shortlist.",
    )
    shortlisted_listing_number: int | None = Field(
        default=None,
        ge=1,
        description="One-based shortlist position to remove and reject.",
    )
