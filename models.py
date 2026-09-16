from datetime import date
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator


Listing = dict[str, Any]
RestrictionSummary = dict[str, str]
RankingResult = dict[str, Any]
RelaxationSuggestion = dict[str, Any]


class ListingCheckSummary(TypedDict):
    database_match_count: int
    checked_count: int
    active_count: int
    unknown_count: int
    inactive_count: int
    unchecked_count: int


class ListingValidationResult(TypedDict):
    ranked_listings: list[RankingResult]
    summary: ListingCheckSummary


ResponseLanguage = Literal["zh", "en"]
PropertyType = Literal[
    "apartment",
    "bungalow_house",
    "cluster_house",
    "condominium",
    "conservation_house",
    "corner_terrace",
    "detached_house",
    "executive_condominium",
    "good_class_bungalow",
    "hdb_flat",
    "semi_detached_house",
    "shophouse",
    "terraced_house",
    "walk_up_apartment",
]
UserIntent = Literal[
    "search",
    "compare_shortlist",
    "show_listing_details",
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
    rental_scope: Literal["entire_unit", "room"] | None = Field(
        default=None,
        description="entire_unit for a whole-unit rental (整租); room for a room in a shared home (合租/单间); null when not stated.",
    )
    property_types: tuple[PropertyType, ...] | None = Field(
        default=None,
        description="Acceptable property types; 公寓 or condo means condominium, executive_condominium, apartment and walk_up_apartment; 组屋 or HDB means hdb_flat; null when not stated.",
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
    min_bedrooms: int | None = Field(
        default=None,
        ge=0,
        description="Minimum number of advertised bedrooms; null when absent.",
    )
    occupant_count: int | None = Field(
        default=None,
        gt=0,
        description="Number of people who need to be allowed to occupy the listing.",
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

    @field_validator("property_types", mode="before")
    @classmethod
    def _no_empty_property_types(cls, value):
        return value or None


class ParsedTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: UserIntent
    preferences: SearchPreferences
    budget_amount: int | None = Field(
        default=None,
        gt=0,
        description="Budget amount stated in this turn before any currency conversion.",
    )
    budget_currency: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 currency code for budget_amount; null when a symbol is ambiguous.",
    )
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
    compare_listing_ids: list[str] = Field(
        default_factory=list,
        description="Explicit listing IDs to compare; empty means compare the shortlist.",
    )
    detail_listing_number: int | None = Field(
        default=None,
        ge=1,
        description="One-based displayed listing position whose details the user wants.",
    )
    shortlisted_listing_number: int | None = Field(
        default=None,
        ge=1,
        description="One-based shortlist position to remove and reject.",
    )
