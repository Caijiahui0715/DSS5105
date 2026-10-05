from datetime import date
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


AMENITY_FIELDS = {
    "food_places": "poi_fnb_1km",
    "hawker": "poi_hawker_1km",
    "libraries": "poi_library_1km",
    "sports": "poi_sport_1km",
    "healthcare": "poi_healthcare_1km",
    "community": "poi_community_1km",
    "schools": "pg_school_count",
}
RankingPriority = Literal[
    "price", "mrt", "amenities", "commute", "space",
    "food_places", "hawker", "libraries", "sports", "healthcare", "community", "schools", "school_distance",
]
# Named priorities share 70% of the ranking weight, so more than three would leave each very little.
MAX_RANKING_PRIORITIES = 3


class NearbyLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str | None = Field(None, min_length=1, description="User-named Singapore place/address/postcode to geocode; never invent coordinates.")
    latitude: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)
    radius_m: float = Field(gt=0, allow_inf_nan=False, description="Maximum straight-line distance in metres, not walking or commute distance.")

    @model_validator(mode="after")
    def _anchor(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Supply both latitude and longitude, or only query to resolve the place.")
        if self.latitude is None and not (self.query and self.query.strip()):
            raise ValueError("A nearby location needs a place query or coordinates.")
        return self


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
    min_area_sqm: float | None = Field(
        default=None,
        gt=0,
        description="Explicit minimum rental area in square metres; convert sqft with 0.09290304. For '空间大一点/宽敞/spacious', use ranking_priority=space and leave this null.",
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
    tenant_gender: Literal["female", "male", "mixed"] | None = Field(
        default=None,
        description=(
            "Gender of the people who will live there, only when the user states it: female, "
            "male, or mixed for a male-female couple or group; null otherwise."
        ),
    )
    landlord_not_living_in: bool = Field(
        default=False,
        description="True when the user does not want the owner or landlord living in the home.",
    )
    furnished_required: bool = Field(
        default=False,
        description="True when the home must come fully or partly furnished.",
    )
    air_conditioning_required: bool = Field(
        default=False,
        description="True when the home must have air conditioning.",
    )
    max_commute_minutes: int | None = Field(
        default=None,
        gt=0,
        description="Maximum public-transport minutes to NUS (Kent Ridge campus); null when absent.",
    )
    min_bathrooms: int | None = Field(None, ge=0, description="Minimum advertised bathrooms; this does not imply a private bathroom.")
    private_bathroom_required: bool = Field(False, description="True only when an explicitly private bathroom is required; never infer it from master_room.")
    pets_allowed_required: bool = Field(False, description="True when the user needs to bring pets; unknown policy does not mean pets are allowed.")
    rent_price_types: tuple[Literal["asking", "negotiable", "starting_from", "guide_price"], ...] | None = Field(None, description="Acceptable advertised price types; negotiable for 可议价; exclude starting_from when the user rejects starting prices.")
    title_keyword: str | None = Field(None, min_length=1, description="User-named development/project to match in listing title, case-insensitive substring.")
    address_keyword: str | None = Field(None, min_length=1, description="Text that must appear in the advertised address; null when absent.")
    street_name: str | None = Field(None, min_length=1, description="Required street name, case-insensitive substring.")
    postcode: str | None = Field(None, pattern=r"^\d{6}$", description="Exact six-digit Singapore postcode, preserving leading zeros.")
    nearby_location: NearbyLocation | None = Field(None, description="Within an explicit radius of a user-named place; query is resolved by the system. Ask for a radius for vague proximity, never guess one.")
    mrt_station: str | None = Field(None, min_length=1, description="Required advertised nearest operating MRT station, e.g. Clementi. Other nearby stations are not identified by this dataset.")
    min_mrt_stations: int | None = Field(None, ge=0, description="Minimum PropertyGuru-reported nearby MRT count; the count does not establish every station is open.")
    max_mrt_distance_m: float | None = Field(None, ge=0, allow_inf_nan=False, description="Maximum walking metres to the advertised nearest operating MRT station.")
    min_food_places: int | None = Field(None, ge=0, description="Minimum F&B places within a straight-line 1 km radius.")
    min_hawker_centres: int | None = Field(None, ge=0, description="Minimum hawker centres within 1 km.")
    min_libraries: int | None = Field(None, ge=0, description="Minimum libraries within 1 km; 附近有图书馆 means 1.")
    min_sports_facilities: int | None = Field(None, ge=0, description="Minimum sports facilities within 1 km.")
    min_healthcare_places: int | None = Field(None, ge=0, description="Minimum hospitals/pharmacies within 1 km; this does not distinguish hospitals from pharmacies.")
    min_community_centres: int | None = Field(None, ge=0, description="Minimum community clubs within 1 km.")
    min_schools: int | None = Field(None, ge=0, description="Minimum PropertyGuru-reported nearby school count, not specifically NUS.")
    max_school_walk_m: float | None = Field(None, ge=0, allow_inf_nan=False, description="Maximum walking metres to the nearest reported school, not a named school or NUS.")
    max_school_walk_minutes: int | None = Field(None, ge=0, description="Maximum reported walking minutes to the nearest school.")
    listed_after: date | None = Field(None, description="Only listings posted on or after this date. Resolve 最近一周 from the supplied current date; this is not move-in availability.")
    furnishing_types: tuple[Literal["fully_furnished", "partially_furnished", "unfurnished", "furnished_unspecified"], ...] | None = Field(None, description="Accepted furnishing levels, e.g. fully_furnished only for 必须全家具; clear incompatible furnished_required when switching to unfurnished.")
    cooking_level: Literal["light", "full", "none"] | None = Field(None, description="light accepts light/full cooking, full requires unrestricted cooking (煎炒), none requires cooking to be prohibited; clear incompatible cooking_required when selecting none.")
    gender_preference: Literal["female", "male"] | None = Field(None, description="Explicitly requested landlord-advertised preferred tenant gender; distinct from occupants' gender and a hard gender restriction. Data is very sparse.")
    ranking_priority: tuple[RankingPriority, ...] = Field(
        default=(),
        description=(
            "Up to three soft preferences the user explicitly asked for, in the order stated; empty "
            "means balanced. price for lower rent, mrt for nearer MRT, amenities for more places to "
            "eat nearby (吃饭方便), commute for a shorter public-transport trip to NUS, space for more "
            "rental area, food_places/hawker/libraries/sports/healthcare/community/schools for more of "
            "that facility, school_distance for a shorter walk to the nearest reported school (not "
            "specifically NUS). The named priorities share 70% of the ranking weight equally."
        ),
    )

    @field_validator("property_types", "rent_price_types", "furnishing_types", mode="before")
    @classmethod
    def _no_empty_property_types(cls, value):
        return value or None

    @field_validator("ranking_priority", mode="before")
    @classmethod
    def _priority_list(cls, value):
        # A single name or "balanced" is still accepted; balanced means no named priority.
        names = [value] if value is None or isinstance(value, str) else value
        names = tuple(dict.fromkeys(name for name in names if name not in (None, "balanced")))
        if len(names) > MAX_RANKING_PRIORITIES:
            raise ValueError(
                f"At most {MAX_RANKING_PRIORITIES} ranking priorities can be saved; ask the user which matter most."
            )
        return names

    @field_validator("title_keyword", "address_keyword", "street_name", "mrt_station")
    @classmethod
    def _strip_search_text(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Search text cannot be empty.")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _compatible_policies(self):
        if self.cooking_required and self.cooking_level == "none":
            raise ValueError("Clear cooking_required before requiring cooking to be prohibited.")
        if self.furnished_required and self.furnishing_types and not any(value != "unfurnished" for value in self.furnishing_types):
            raise ValueError("Clear furnished_required before requiring an unfurnished home.")
        return self


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
    budget_months: int = Field(
        default=1,
        ge=1,
        le=36,
        description="Months budget_amount covers: 12 for a yearly budget (一年, 每年, 年预算, per year), the lease length for a whole-lease total, otherwise 1.",
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
