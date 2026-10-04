from models import (
    Listing,
    ListingCheckSummary,
    RankingResult,
    RelaxationSuggestion,
    ResponseLanguage,
    RestrictionSummary,
    SearchPreferences,
    UserIntent,
)
from tools import AMENITY_FIELDS, EXTRA_CONDITION_LABELS, mrt_minutes


_FACTOR_LABELS = {
    "zh": {"price": "价格", "mrt": "MRT", "food": "周边餐饮", "commute": "到 NUS 通勤", "space": "空间大小"},
    "en": {"price": "price", "mrt": "MRT", "food": "nearby food", "commute": "commute to NUS", "space": "space"},
}

_RESTRICTION_TEXT = {
    "zh": {
        ("cooking", "allowed"): "允许做饭",
        ("cooking", "light_only"): "仅允许简单烹饪",
        ("cooking", "not_allowed"): "不允许做饭",
        ("owner_staying", "yes"): "房东同住",
        ("owner_staying", "no"): "房东不同住",
        ("tenant_gender", "female_only"): "仅限女性租客",
        ("tenant_gender", "male_only"): "仅限男性租客",
        ("tenant_gender", "male_preferred"): "偏好男性租客",
        ("tenant_gender", "female_preferred"): "偏好女性租客",
        ("tenant_gender", "no_restriction"): "不限租客性别",
        ("furnishing", "fully_furnished"): "全家具",
        ("furnishing", "partially_furnished"): "部分家具",
        ("furnishing", "furnished_unspecified"): "带家具（程度未注明）",
        ("furnishing", "unfurnished"): "无家具",
        ("air_conditioning", "yes"): "有空调",
        ("air_conditioning", "no"): "无空调",
        ("visitors", "not_allowed"): "不允许访客",
        ("smoking", "not_allowed"): "禁止吸烟",
    },
    "en": {
        ("cooking", "allowed"): "cooking allowed",
        ("cooking", "light_only"): "light cooking only",
        ("cooking", "not_allowed"): "no cooking",
        ("owner_staying", "yes"): "owner staying",
        ("owner_staying", "no"): "owner not staying",
        ("tenant_gender", "female_only"): "female tenants only",
        ("tenant_gender", "male_only"): "male tenants only",
        ("tenant_gender", "male_preferred"): "male tenant preferred",
        ("tenant_gender", "female_preferred"): "female tenant preferred",
        ("tenant_gender", "no_restriction"): "any tenant gender",
        ("furnishing", "fully_furnished"): "fully furnished",
        ("furnishing", "partially_furnished"): "partially furnished",
        ("furnishing", "furnished_unspecified"): "furnished (level not stated)",
        ("furnishing", "unfurnished"): "unfurnished",
        ("air_conditioning", "yes"): "air conditioning",
        ("air_conditioning", "no"): "no air conditioning",
        ("visitors", "not_allowed"): "no visitors",
        ("smoking", "not_allowed"): "no smoking",
    },
}

_WARNING_TEXT = {
    "zh": {
        "area_outside_review_range": "广告面积小于 80 sqft，请核实面积和单位",
        "headline_tenant_count_conflict": "广告标题与平台最大入住人数不一致",
        "rent_outside_review_range": "该房源属于高价房源，请核实报价",
        "live_status_unknown": "目前无法确认该链接是否仍然有效",
    },
    "en": {
        "area_outside_review_range": "the advertised area is below 80 sqft; verify the area and unit",
        "headline_tenant_count_conflict": "the headline conflicts with the platform occupancy limit",
        "rent_outside_review_range": "this is a high-rent listing; verify the asking rent",
        "live_status_unknown": "the listing link could not currently be verified",
    },
}

_AVAILABILITY_TEXT = {
    "zh": {
        "ready_at_snapshot": "采集时标注可入住",
        "date_missing_year": "广告提供了日期，但年份无法确认",
        "unknown": "未注明",
    },
    "en": {
        "ready_at_snapshot": "marked available when collected",
        "date_missing_year": "a date was advertised, but its year is unconfirmed",
        "unknown": "not stated",
    },
}

PREFERENCE_LABELS = {
    "zh": {
        "max_price_sgd": "每月最高预算",
        "room_type": "房型",
        "room_type_flexible": "房型不限",
        "rental_scope": "出租方式",
        "property_types": "物业类型",
        "district_code": "地区",
        "max_mrt_minutes": "MRT 步行上限（分钟）",
        "min_bedrooms": "最少卧室数",
        "min_area_sqm": "最低出租面积（平方米）",
        "occupant_count": "入住人数",
        "move_in_date": "入住日期",
        "move_in_flexible": "入住日期灵活",
        "cooking_required": "需要做饭",
        "tenant_gender": "租客性别",
        "landlord_not_living_in": "不要房东同住",
        "furnished_required": "需要家具",
        "air_conditioning_required": "需要空调",
        "max_commute_minutes": "到 NUS 公共交通上限（分钟）",
        "ranking_priority": "排序偏好",
    },
    "en": {
        "max_price_sgd": "maximum monthly budget",
        "room_type": "room type",
        "room_type_flexible": "any room type",
        "rental_scope": "rental type",
        "property_types": "property types",
        "district_code": "district",
        "max_mrt_minutes": "MRT walking limit (minutes)",
        "min_bedrooms": "minimum bedrooms",
        "min_area_sqm": "minimum rental area (sqm)",
        "occupant_count": "occupants",
        "move_in_date": "move-in date",
        "move_in_flexible": "flexible move-in date",
        "cooking_required": "cooking required",
        "tenant_gender": "tenant gender",
        "landlord_not_living_in": "no live-in landlord",
        "furnished_required": "furnished",
        "air_conditioning_required": "air conditioning",
        "max_commute_minutes": "public-transport limit to NUS (minutes)",
        "ranking_priority": "ranking priority",
    },
}

_CONDITION_LABELS = {
    "zh": {
        "max_price_sgd": "预算",
        "district_code": "地区",
        "room_type": "房型",
        "rental_scope": "整租/合租",
        "property_types": "物业类型",
        "max_mrt_minutes": "MRT 步行时间",
        "min_bedrooms": "卧室数",
        "min_area_sqm": "出租面积",
        "occupant_count": "可入住人数",
        "cooking_required": "做饭政策",
        "tenant_gender": "租客性别限制",
        "landlord_not_living_in": "房东是否同住",
        "furnished_required": "家具",
        "air_conditioning_required": "空调",
        "max_commute_minutes": "到 NUS 通勤时间",
        "nearby_food": "周边餐饮",
    },
    "en": {
        "max_price_sgd": "budget",
        "district_code": "district",
        "room_type": "room type",
        "rental_scope": "whole unit or room",
        "property_types": "property type",
        "max_mrt_minutes": "MRT walking time",
        "min_bedrooms": "bedrooms",
        "min_area_sqm": "rental area",
        "occupant_count": "occupancy limit",
        "cooking_required": "cooking policy",
        "tenant_gender": "tenant gender rule",
        "landlord_not_living_in": "whether the landlord lives in",
        "furnished_required": "furnishing",
        "air_conditioning_required": "air conditioning",
        "max_commute_minutes": "commute time to NUS",
        "nearby_food": "nearby food",
    },
}

_CONDITION_STATUS_TEXT = {
    "zh": {"pass": "符合", "fail": "不符合", "unknown": "未注明"},
    "en": {"pass": "meets", "fail": "fails", "unknown": "not stated"},
}

_SOURCE_TEXT = {
    "zh": {"listing_card": "房源卡片", "rechecked_listing": "重新采集的现价", "onemap_walking_route": "OneMap 步行路线", "onemap_public_transport_route": "OneMap 公共交通路线", None: "无数据"},
    "en": {"listing_card": "the listing card", "rechecked_listing": "the rechecked current price", "onemap_walking_route": "a OneMap walking route", "onemap_public_transport_route": "a OneMap public-transport route", None: "no data"},
}

_FACTOR_FORMULAS = {
    "zh": {
        "price": "月租 ÷ 预算上限",
        "mrt": "到已通车 MRT 站的步行米数 ÷ 参考距离（米数上限或分钟上限 × 85 米，两者取小；均未指定时 850 米）",
        "commute": "到 NUS 公共交通分钟 ÷ 通勤上限（没给上限时 45 分钟）",
        "food": "按 1 公里内餐饮和小贩中心数在全部房源里的排位",
        "space": "同一出租方式和面积口径内，广告面积从大到小的百分位（0 最大）",
    },
    "en": {
        "price": "rent ÷ budget",
        "mrt": "walking metres to an operating MRT station ÷ reference (metres limit or minutes × 85 m, the smaller when both are given; 850 m without either)",
        "commute": "public-transport minutes to NUS ÷ commute limit (45 minutes without a limit)",
        "food": "position among all listings on F&B and hawker centres within 1 km",
        "space": "descending area percentile within the same rental type and area scope (0 is largest)",
    },
}
_NO_DATA_FACTOR = {
    "zh": {"mrt": "没有数据或车站尚未通车，按参考距离计 1", "commute": "没有数据，按上限计 1", "food": "没有数据，按中间排位计 0.5", "space": "出租面积未注明或口径不符，按中间排位计 0.5"},
    "en": {"mrt": "no data or the station is not open yet, so it counts as the reference, 1", "commute": "no data, so it counts as the limit, 1", "food": "no data, so it counts as the middle position, 0.5", "space": "rental area is unstated or its scope does not match; counts as the middle position, 0.5"},
}


_AMENITY_LABELS = {
    "food_places": ("餐饮点", "F&B places"), "hawker": ("小贩中心", "hawker centres"),
    "libraries": ("图书馆", "libraries"), "sports": ("体育设施", "sports facilities"),
    "healthcare": ("医疗设施", "healthcare places"), "community": ("民众俱乐部", "community clubs"),
    "schools": ("周边学校", "nearby schools"), "school_distance": ("最近学校步行距离", "walk to the nearest school"),
}
for language, index in (("zh", 0), ("en", 1)):
    labels = {field: pair[index] for field, pair in EXTRA_CONDITION_LABELS.items()}
    PREFERENCE_LABELS[language].update(labels)
    _CONDITION_LABELS[language].update(labels)
    _FACTOR_LABELS[language].update({name: pair[index] for name, pair in _AMENITY_LABELS.items()})
    _CONDITION_LABELS[language].update({name: pair[index] for name, pair in _AMENITY_LABELS.items()})
    for name in AMENITY_FIELDS:
        label = _AMENITY_LABELS[name][index]
        _FACTOR_FORMULAS[language][name] = f"按{label}数量在全部有数据房源里的排位（越小选择越多）" if language == "zh" else f"descending position among all listings with {label} counts (lower means more choice)"
        _NO_DATA_FACTOR[language][name] = _NO_DATA_FACTOR[language]["food"]
    _FACTOR_FORMULAS[language]["school_distance"] = "最近学校步行分钟 ÷ 参考上限（未指定时 10 分钟）" if language == "zh" else "walking minutes to the nearest school ÷ limit (10 minutes without a limit)"
    _NO_DATA_FACTOR[language]["school_distance"] = _NO_DATA_FACTOR[language]["commute"]
    _RESTRICTION_TEXT[language].update({
        ("pets", "allowed"): "允许宠物" if language == "zh" else "pets allowed",
        ("pets", "not_allowed"): "不允许宠物" if language == "zh" else "no pets",
        ("private_bathroom", "yes"): "独立卫浴" if language == "zh" else "private bathroom",
        ("private_bathroom", "no"): "无独立卫浴" if language == "zh" else "no private bathroom",
    })


def render_response(
    ranked_listings: list[RankingResult] | None = None,
    restrictions: dict[str, RestrictionSummary] | None = None,
    relaxations: list[RelaxationSuggestion] | None = None,
    *,
    heading: str | None = None,
    limit: int = 3,
    language: ResponseLanguage = "zh",
    check_summary: ListingCheckSummary | None = None,
    start: int = 1,
) -> str:
    ranked_listings = ranked_listings or []
    restrictions = restrictions or {}
    if not ranked_listings:
        response = _render_relaxations(relaxations or [], language)
        if check_summary:
            response = f"{_check_summary_text(check_summary, language)}\n\n{response}"
        return response

    lines = [
        heading
        or _text(
            language,
            f"找到 {len(ranked_listings)} 套符合条件的房源，以下按匹配度排序：",
            f"Found {len(ranked_listings)} matching listings, ranked by fit:",
        )
    ]
    if check_summary:
        lines.append(_check_summary_text(check_summary, language))
    for index, item in enumerate(ranked_listings[:limit], start):
        listing = item["listing"]
        listing_id = listing["listing_id"]
        price = listing.get("rent_monthly_sgd")
        lines.extend(
            [
                "",
                f"{index}. {listing.get('title') or _text(language, '未命名房源', 'Untitled listing')} ({listing_id})",
                _text(
                    language,
                    f"   月租：{f'S${price:,}' if isinstance(price, (int, float)) else '未知'}",
                    f"   Monthly rent: {f'S${price:,}' if isinstance(price, (int, float)) else 'unknown'}",
                ),
                _text(
                    language,
                    f"   MRT：{_mrt_text(listing, language)}",
                    f"   MRT: {_mrt_text(listing, language)}",
                ),
            ]
        )
        if commute := _commute_text(listing, language):
            lines.append(_text(language, f"   到 NUS：{commute}", f"   To NUS: {commute}"))
        lines.append(_text(language, f"   面积：{_area_text(listing, language)}", f"   Area: {_area_text(listing, language)}"))
        if listing.get("bathrooms") is not None:
            lines.append(_text(language, f"   卫生间：{listing['bathrooms']} 个", f"   Bathrooms: {listing['bathrooms']}"))

        factors = item.get("factors", {})
        weights = [
            f"{_FACTOR_LABELS[language].get(name, name)} {round(factor['weight'] * 100)}%"
            for name, factor in factors.items()
        ]
        if weights:
            lines.append(
                _text(
                    language,
                    f"   排名权重：{'，'.join(weights)}",
                    f"   Ranking weights: {', '.join(weights)}",
                )
            )

        if listing.get("availability_status"):
            lines.append(
                _text(
                    language,
                    f"   入住状态：{_availability_text(listing, language)}",
                    f"   Availability: {_availability_text(listing, language)}",
                )
            )

        rules = [
            text
            for key, value in restrictions.get(listing_id, {}).items()
            if (text := _RESTRICTION_TEXT[language].get((key, value)))
        ]
        if rules:
            lines.append(
                _text(
                    language,
                    f"   条件：{'；'.join(rules)}",
                    f"   Conditions: {'; '.join(rules)}",
                )
            )
        if listing.get("unknown_conditions"):
            separator = "、" if language == "zh" else ", "
            unstated = separator.join(
                _CONDITION_LABELS[language][field] for field in listing["unknown_conditions"]
            )
            lines.append(_text(language, f"   需确认（数据未注明）：{unstated}", f"   To confirm (not stated): {unstated}"))
        if item.get("warnings"):
            lines.append(
                _text(
                    language,
                    f"   数据提示：{'；'.join(_warning_text(flag, language, listing) for flag in item['warnings'])}",
                    f"   Data notes: {'; '.join(_warning_text(flag, language, listing) for flag in item['warnings'])}",
                )
            )

    return "\n".join(lines)


def render_intent_response(
    intent: UserIntent,
    ranked_listings: list[RankingResult] | None = None,
    restrictions: dict[str, RestrictionSummary] | None = None,
    relaxations: list[RelaxationSuggestion] | None = None,
    language: ResponseLanguage = "zh",
    *,
    check_summary: ListingCheckSummary | None = None,
) -> str:
    if intent == "show_results":
        if ranked_listings:
            return render_response(
                ranked_listings, restrictions, language=language, check_summary=check_summary
            )
        if relaxations:
            suggestion = relaxations[0]
            return (
                _text(
                    language,
                    f"目前没有可展示的严格匹配房源。是否接受{_relaxation_change(suggestion, language)}？"
                    f"{_relaxation_count_text(suggestion, language)}",
                    f"There are currently no strict matches to display. Would you accept "
                    f"{_relaxation_change(suggestion, language)}? "
                    f"{_relaxation_count_text(suggestion, language)}",
                )
            )
        return _text(language, "目前没有可展示的房源，请先告诉我你的租房要求。", "There are no listings to show yet. Please tell me your rental requirements first.")
    if intent == "reject_relaxation":
        return _text(language, "好的，我会保留原来的搜索条件。你可以告诉我想调整哪项要求。", "Okay, I will keep the original search criteria. Tell me which requirement you want to change.")
    if intent == "reject_results":
        return _text(language, "目前没有已展示的房源可以排除，请先搜索或查看房源。", "There are no displayed listings to exclude. Please search for or view listings first.")
    if intent == "accept_relaxation":
        return _text(language, "目前没有可接受的让步建议，请告诉我想调整的搜索条件。", "There is no pending relaxation to accept. Tell me which search condition you want to change.")
    return _text(language, "我还不确定你想搜索、修改条件还是查看房源，请再说明一下。", "I am not sure whether you want to search, change criteria, or view listings. Please clarify.")


def render_comparison(
    ranked_listings: list[RankingResult],
    restrictions: dict[str, RestrictionSummary],
    language: ResponseLanguage = "zh",
) -> str:
    if len(ranked_listings) < 2:
        return _text(language, "至少需要两套可用房源才能进行比较。", "At least two available listings are needed for a comparison.")

    lines = [
        render_response(
            ranked_listings,
            restrictions,
            heading=_text(language, f"正在比较 {len(ranked_listings)} 套房源：", f"Comparing {len(ranked_listings)} listings:"),
            limit=len(ranked_listings),
            language=language,
        ),
        "",
        _text(language, "关键差异：", "Key differences:"),
    ]
    listings = [item["listing"] for item in ranked_listings]
    priced = [
        listing
        for listing in listings
        if isinstance(listing.get("rent_monthly_sgd"), (int, float))
    ]
    if priced:
        cheapest = min(priced, key=lambda listing: listing["rent_monthly_sgd"])
        lines.append(
            _text(
                language,
                f"- 最低月租：{cheapest['listing_id']}（S${cheapest['rent_monthly_sgd']:,}）",
                f"- Lowest rent: {cheapest['listing_id']} (S${cheapest['rent_monthly_sgd']:,})",
            )
        )

    with_mrt = [
        (listing, mrt_minutes(listing))
        for listing in listings
        if mrt_minutes(listing) is not None
    ]
    if with_mrt:
        closest, minutes = min(with_mrt, key=lambda item: item[1])
        lines.append(_text(language, f"- MRT 最近：{closest['listing_id']}（约 {minutes} 分钟）", f"- Closest MRT: {closest['listing_id']} (about {minutes} minutes)"))
    else:
        lines.append(_text(language, "- MRT：这些房源目前都没有可用的步行时间", "- MRT: no walking-time data is available for these listings"))
    return "\n".join(lines)


def render_listing_details(
    listing: Listing,
    restrictions: RestrictionSummary,
    language: ResponseLanguage = "zh",
) -> str:
    price = listing.get("rent_monthly_sgd")
    bedrooms = listing.get("bedrooms")
    bathrooms = listing.get("bathrooms")
    occupants = listing.get("tenant_count_reported")
    lines = [
        _text(language, f"房源详情：{listing.get('title') or '未命名房源'}（{listing['listing_id']}）", f"Listing details: {listing.get('title') or 'Untitled listing'} ({listing['listing_id']})"),
        _text(language, f"- 月租：{f'S${price:,}' if isinstance(price, (int, float)) else '未知'}", f"- Monthly rent: {f'S${price:,}' if isinstance(price, (int, float)) else 'unknown'}"),
        _text(language, f"- 房型：{_display(listing.get('room_type'), '未知')}", f"- Room type: {_display(listing.get('room_type'), 'unknown')}"),
        _text(language, f"- 出租范围：{_display(listing.get('rental_scope'), '未知')}", f"- Rental scope: {_display(listing.get('rental_scope'), 'unknown')}"),
        _text(language, f"- 物业类型：{_display(listing.get('property_type'), '未知')}", f"- Property type: {_display(listing.get('property_type'), 'unknown')}"),
        _text(language, f"- 卧室/卫生间：{bedrooms if bedrooms is not None else '未知'} / {bathrooms if bathrooms is not None else '未知'}", f"- Bedrooms/bathrooms: {bedrooms if bedrooms is not None else 'unknown'} / {bathrooms if bathrooms is not None else 'unknown'}"),
        _text(language, f"- 面积：{_area_text(listing, language)}", f"- Area: {_area_text(listing, language)}"),
        _text(language, f"- 最大入住人数：{occupants if occupants is not None else '未注明'}", f"- Maximum occupants: {occupants if occupants is not None else 'not stated'}"),
        _text(language, f"- 地区：{listing.get('district_code') or '未知'}", f"- District: {listing.get('district_code') or 'unknown'}"),
        _text(language, f"- 地址：{listing.get('address') or '未知'}", f"- Address: {listing.get('address') or 'unknown'}"),
        _text(language, f"- MRT：{listing.get('mrt_station') or '车站未知'}，{_mrt_text(listing, language)}", f"- MRT: {listing.get('mrt_station') or 'unknown station'}, {_mrt_text(listing, language)}"),
        _text(language, f"- 到 NUS：{_commute_text(listing, language)}", f"- To NUS: {_commute_text(listing, language)}") if listing.get("commute_nus_minutes") is not None else "",
        _text(language, f"- 入住状态：{_availability_text(listing, language)}", f"- Availability: {_availability_text(listing, language)}"),
        _nearby_text(listing, language),
        _text(language, f"- 链接状态：{_link_status_text(listing, language)}", f"- Link status: {_link_status_text(listing, language)}"),
        _text(language, f"- 房源链接：{listing.get('final_url') or listing.get('listing_url')}", f"- Listing URL: {listing.get('final_url') or listing.get('listing_url')}"),
    ]
    rules = [
        text
        for key, value in restrictions.items()
        if (text := _RESTRICTION_TEXT[language].get((key, value)))
    ]
    if rules:
        lines.append(_text(language, f"- 居住条件：{'；'.join(rules)}", f"- Conditions: {'; '.join(rules)}"))
    if listing.get("review_flags"):
        lines.append(_text(language, f"- 数据提示：{'；'.join(_warning_text(flag, language) for flag in listing['review_flags'])}", f"- Data notes: {'; '.join(_warning_text(flag, language) for flag in listing['review_flags'])}"))
    return "\n".join(line for line in lines if line)


def render_relaxation_preview(
    suggestion: RelaxationSuggestion,
    ranked_listings: list[RankingResult],
    restrictions: dict[str, RestrictionSummary],
    language: ResponseLanguage = "zh",
    *,
    check_summary: ListingCheckSummary | None = None,
) -> str:
    if not ranked_listings:
        response = _text(
            language,
            f"按“{_relaxation_change(suggestion, language)}”预览，尚未修改你的原搜索条件。该让步本次暂时没有可展示的房源。",
            f"Previewing results after {_relaxation_change(suggestion, language)}; your original criteria have not changed. There are currently no listings to display under that relaxation.",
        )
        return f"{response}\n\n{_check_summary_text(check_summary, language)}" if check_summary else response
    return _text(
        language,
        f"按“{_relaxation_change(suggestion, language)}”预览，尚未修改你的原搜索条件：\n\n"
        f"{render_response(ranked_listings, restrictions, language=language, check_summary=check_summary)}",
        f"Previewing results after {_relaxation_change(suggestion, language)}; your original search criteria have not changed:\n\n"
        f"{render_response(ranked_listings, restrictions, language=language, check_summary=check_summary)}",
    )


def render_needs_confirmation(
    ranked_listings: list[RankingResult],
    restrictions: dict[str, RestrictionSummary],
    language: ResponseLanguage = "zh",
    *,
    start: int = 1,
    check_summary: ListingCheckSummary | None = None,
) -> str:
    if not ranked_listings:
        return ""
    return render_response(
        ranked_listings,
        restrictions,
        heading=_text(
            language,
            "以下房源其他已知条件都符合，但部分要求在数据中未注明，需要你向发布方确认：",
            "These listings meet every known condition, but some requirements are not stated in the data and need your confirmation with the publisher:",
        ),
        limit=len(ranked_listings),
        language=language,
        check_summary=check_summary,
        start=start,
    )


def render_decision_context(rows: list[dict], language: ResponseLanguage = "zh") -> str:
    helpful = sorted(
        (row for row in rows if row["database_matches_without_it"]),
        key=lambda row: row["database_matches_without_it"],
        reverse=True,
    )
    if not helpful:
        return _text(
            language,
            "单独放开任何一个条件，数据库中仍没有符合其余条件的房源。",
            "Relaxing any single condition still leaves no database listing that meets the rest.",
        )
    lines = [
        _text(
            language,
            "结果主要被以下条件卡住（数据库匹配数，尚未检查链接）：",
            "Results are mainly blocked by these conditions (database counts before link checks):",
        )
    ]
    for row in helpful:
        label = _CONDITION_LABELS[language][row["condition"]]
        count = row["database_matches_without_it"]
        line = _text(
            language,
            f"- 放开「{label}」：{count} 套符合其余条件",
            f"- Without the {label} condition: {count} listings meet the rest",
        )
        if row["unknown"]:
            line += _text(
                language,
                f"，其中 {row['unknown']} 套只是没有注明该项",
                f", and {row['unknown']} of them simply do not state it",
            )
        limit = row.get("smallest_limit_with_a_match")
        if limit is not None and row["condition"] == "max_price_sgd":
            line += _text(language, f"；预算至少 S${limit:,} 才有完全符合的房源", f"; a budget of at least S${limit:,} gives a full match")
        elif limit is not None:
            line += _text(language, f"；MRT 步行上限至少 {limit} 分钟才有完全符合的房源", f"; an MRT limit of at least {limit} minutes gives a full match")
        lines.append(line)
    return "\n".join(lines)


def render_listing_explanation(explanation: dict, language: ResponseLanguage = "zh") -> str:
    listing_id = explanation["listing_id"]
    score = _display(explanation["rank_value"], _text(language, "无可计算项", "not computable"))
    lines = [
        _text(
            language,
            f"房源 {listing_id} 的排序依据（综合值越小越靠前）：综合值 {score}",
            f"Why listing {listing_id} ranks where it does (lower scores rank higher): score {score}",
        )
    ]
    for name, factor in explanation["factors"].items():
        weight = round(factor["weight"] * 100)
        value = _NO_DATA_FACTOR[language][name] if factor.get("no_data") else factor["ratio"]
        lines.append(
            _text(
                language,
                f"- {_FACTOR_LABELS['zh'][name]}：{_FACTOR_FORMULAS['zh'][name]} = {value}，权重 {weight}%",
                f"- {_FACTOR_LABELS['en'][name]}: {_FACTOR_FORMULAS['en'][name]} = {value}, weight {weight}%",
            )
        )
    if explanation["conditions"]:
        separator = "；" if language == "zh" else "; "
        checks = separator.join(
            f"{_CONDITION_LABELS[language][field]} {_CONDITION_STATUS_TEXT[language][status]}"
            for field, status in explanation["conditions"].items()
        )
        lines.append(_text(language, f"- 条件核对：{checks}", f"- Conditions: {checks}"))
    rent_source = _SOURCE_TEXT[language][explanation["sources"]["rent_monthly_sgd"]]
    mrt_source = _SOURCE_TEXT[language][explanation["sources"]["mrt_minutes"]]
    commute_source = explanation["sources"].get("commute_nus_minutes")
    commute = _text(language, f"，到 NUS 通勤时间来自{_SOURCE_TEXT['zh'][commute_source]}", f", commute to NUS from {_SOURCE_TEXT['en'][commute_source]}") if commute_source else ""
    lines.append(
        _text(
            language,
            f"- 数据来源：月租来自{rent_source}，MRT 时间来自{mrt_source}{commute}；采集时间 {explanation['collected_at']}",
            f"- Sources: rent from {rent_source}, MRT time from {mrt_source}{commute}; collected at {explanation['collected_at']}",
        )
    )
    rent, card_rent = explanation["rent_monthly_sgd"], explanation.get("rent_monthly_sgd_card")
    if card_rent not in (None, rent):
        lines.append(
            _text(
                language,
                f"- 价格变化：采集时房源卡片为 S${card_rent:,}，现价 S${rent:,}；下面的原文是采集时的内容",
                f"- Price change: the listing card showed S${card_rent:,} when collected and the current price is S${rent:,}; the source text below is from collection time",
            )
        )
    card_text = (explanation.get("evidence") or {}).get("card_text")
    if card_text:
        lines.append(_text(language, f"- 原文：{card_text}", f"- Source text: {card_text}"))
    lines.append(_text(language, f"- 房源链接：{explanation['listing_url']}", f"- Listing URL: {explanation['listing_url']}"))
    return "\n".join(lines)


def render_budget_ladder(
    rows: list[dict],
    saved_budget: int | None,
    strict_grows: bool,
    language: ResponseLanguage = "zh",
) -> str:
    lines = [
        _text(
            language,
            "不同预算下的房源数量（数据库筛选，尚未检查链接；你保存的条件没有修改）：",
            "Listings at different budgets (database counts before link checks; your saved criteria have not changed):",
        )
    ]
    for row in rows:
        budget, strict, pending = row["max_price_sgd"], row["strict_matches"], row["needs_confirmation"]
        if budget is None:
            label = _text(language, "不限预算", "No budget limit")
        elif budget == saved_budget:
            label = _text(language, f"当前 S${budget:,}", f"Current S${budget:,}")
        else:
            label = f"S${budget:,}"
        line = _text(
            language,
            f"- {label}：完全符合 {strict['count']} 套；需确认 {pending['count']} 套，其中 {pending['mrt_within_10_min']} 套步行 10 分钟内到 MRT",
            f"- {label}: full matches {strict['count']}; to confirm {pending['count']}, of which {pending['mrt_within_10_min']} within 10 minutes of MRT",
        )
        cheapest = [group["cheapest_entire_unit_sgd"] for group in (strict, pending) if group["entire_unit"]]
        if cheapest:
            count = strict["entire_unit"] + pending["entire_unit"]
            line += _text(
                language,
                f"；明确整租 {count} 套（最低 S${min(cheapest):,}）",
                f"; explicit whole units {count} (from S${min(cheapest):,})",
            )
        lines.append(line)
    if not strict_grows:
        lines.append(_text(language, "提高预算不会增加完全符合条件的房源。", "A higher budget does not add listings that meet every condition."))
    return "\n".join(lines)


def render_preference_changes(
    before: SearchPreferences,
    changes: dict,
    language: ResponseLanguage = "zh",
) -> str:
    separator = "；" if language == "zh" else "; "
    changed = separator.join(
        f"{PREFERENCE_LABELS[language][field]} {_preference_value(getattr(before, field), language)} → {_preference_value(value, language)}"
        for field, value in changes.items()
    )
    return _text(language, f"已保存条件变更：{changed}", f"Saved preference changes: {changed}")


def render_link_checks(checks: list[dict], language: ResponseLanguage = "zh") -> str:
    lines = [_text(language, "链接检查：", "Link checks:")]
    lines.extend(
        _text(
            language,
            f"- {check['title']}（{check['listing_id']}）：{check['note']}。",
            f"- {check['title']} ({check['listing_id']}): {check['note']}.",
        )
        for check in checks
    )
    return "\n".join(lines)


def render_saved_preferences(preferences: SearchPreferences, language: ResponseLanguage = "zh") -> str:
    saved = preferences.model_dump(exclude_defaults=True)
    if not saved:
        return _text(language, "目前还没有保存搜索条件。", "No search criteria are saved yet.")
    separator = "；" if language == "zh" else "; "
    items = separator.join(
        f"{PREFERENCE_LABELS[language][field]} {_preference_value(value, language)}"
        for field, value in saved.items()
    )
    return _text(language, f"当前保存的条件：{items}", f"Saved criteria: {items}")


def _preference_value(value: object, language: ResponseLanguage) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict) and "radius_m" in value:
        anchor = value.get("query") or f"({value.get('latitude')}, {value.get('longitude')})"
        return _text(language, f"{anchor} 直线 {value['radius_m']:g} 米内", f"within {value['radius_m']:g} m straight-line of {anchor}")
    if value is None:
        return _text(language, "不限", "any")
    if isinstance(value, bool):
        return _text(language, "是" if value else "否", "yes" if value else "no")
    if isinstance(value, (list, tuple)):
        return ("、" if language == "zh" else ", ").join(_preference_value(item, language) for item in value)
    if value in _AMENITY_LABELS:
        label = _AMENITY_LABELS[value]
        return _text(language, f"{label[0]}优先", f"prioritise {label[1]}")
    label = {
        "entire_unit": ("整租", "whole unit"),
        "room": ("合租/单间", "room"),
        "balanced": ("均衡", "balanced"),
        "price": ("价格优先", "lower price"),
        "mrt": ("离 MRT 近", "nearer MRT"),
        "amenities": ("吃饭方便", "more food nearby"),
        "commute": ("到 NUS 通勤近", "shorter commute to NUS"),
        "space": ("空间大优先", "more space"),
        "female": ("女性", "female"),
        "male": ("男性", "male"),
        "mixed": ("男女同住", "mixed male and female"),
        "fully_furnished": ("全家具", "fully furnished"),
        "partially_furnished": ("部分家具", "partly furnished"),
        "unfurnished": ("无家具", "unfurnished"),
        "furnished_unspecified": ("带家具，程度未注明", "furnished, level unstated"),
        "light": ("允许轻炊或不限烹饪", "light or unrestricted cooking"),
        "full": ("不限烹饪", "unrestricted cooking"),
        "none": ("禁止做饭", "cooking prohibited"),
        "asking": ("要价", "asking price"),
        "negotiable": ("可议价", "negotiable"),
        "starting_from": ("起价", "starting price"),
        "guide_price": ("指导价", "guide price"),
    }.get(value)
    return _text(language, *label) if label else str(value)


def _area_text(listing: dict, language: ResponseLanguage) -> str:
    area = listing.get("area_sqm")
    if not isinstance(area, (int, float)) or area <= 0:
        return _text(language, "未注明", "not stated")
    scope = {
        "floor_reported": ("广告整套面积", "advertised whole-home area"),
        "room_reported": ("广告房间面积", "advertised room area"),
    }.get(listing.get("area_scope"), ("广告面积，范围未注明", "advertised area, scope unstated"))
    text = _text(language, f"{area:,.2f}㎡（{scope[0]}）", f"{area:,.2f} sqm ({scope[1]})")
    if listing.get("rental_scope") == "room" and listing.get("area_scope") == "floor_reported":
        text += _text(language, "；房间面积未注明", "; room area not stated")
    return text


def _mrt_text(listing: dict, language: ResponseLanguage) -> str:
    if listing.get("mrt_operation_status") == "under_construction":
        return _text(language, "最近的车站尚未通车，不计入 MRT 步行时间", "the nearest station is not open yet, so no MRT walking time counts")
    minutes = mrt_minutes(listing)
    if listing.get("mrt_walk_minutes") is not None:
        distance = listing.get("mrt_walk_distance_m")
        suffix = _text(language, f"（{distance:,} 米）", f" ({distance:,} m)") if isinstance(distance, (int, float)) else ""
        return _text(language, f"OneMap 步行约 {minutes} 分钟{suffix}", f"about {minutes} minutes on foot via OneMap{suffix}")

    distance = listing.get("mrt_distance_m")
    suffix = _text(language, f"（{distance:,.0f} 米）", f" ({distance:,.0f} m)") if isinstance(distance, (int, float)) else ""
    return _text(language, f"房源描述约 {minutes} 分钟{suffix}", f"about {minutes} minutes according to the listing{suffix}") if minutes is not None else _text(language, "时间未知", "walking time unknown")


def _commute_text(listing: dict, language: ResponseLanguage) -> str:
    minutes = listing.get("commute_nus_minutes")
    if minutes is None:
        return ""
    return _text(language, f"公共交通约 {minutes:g} 分钟", f"about {minutes:g} minutes by public transport")


def render_rental_scope_mix(mix: dict, language: ResponseLanguage = "zh") -> str:
    """Name the kind of listing shown when the user has not chosen a whole unit or a room."""
    whole_unit, room = mix["entire_unit"], mix["room"]
    if mix["shown_scopes"] == ["room"]:
        text = _text(
            language,
            f"提示：展示的都是合租房间；数据库里符合条件的整租有 {whole_unit['database_count']} 套，最低 S${whole_unit['cheapest_sgd']:,}。",
            f"Note: the listings shown are all rooms; the database has {whole_unit['database_count']} whole units meeting your criteria, from S${whole_unit['cheapest_sgd']:,}.",
        )
    elif mix["shown_scopes"] == ["entire_unit"]:
        text = _text(
            language,
            f"提示：展示的都是整租；数据库里符合条件的合租房间有 {room['database_count']} 套，最低 S${room['cheapest_sgd']:,}。",
            f"Note: the listings shown are all whole units; the database has {room['database_count']} rooms meeting your criteria, from S${room['cheapest_sgd']:,}.",
        )
    else:
        text = _text(
            language,
            f"提示：结果里整租和合租房间混在一起（数据库里整租 {whole_unit['database_count']} 套、合租 {room['database_count']} 套）。",
            f"Note: the results mix whole units and rooms (the database has {whole_unit['database_count']} whole units and {room['database_count']} rooms).",
        )
    return text + _text(language, "想只看一种，告诉我要整租还是合租即可。", " Tell me whether you want a whole unit or a room to see only one kind.")


def _render_relaxations(relaxations: list[RelaxationSuggestion], language: ResponseLanguage) -> str:
    if not relaxations:
        return _text(language, "当前没有可展示的严格匹配房源，单项小幅放宽后也暂未找到经检查可展示的候选。", "There are currently no strict matches to display, and no checked candidates could be displayed after a single small relaxation.")

    lines = [_text(language, "当前没有可展示的严格匹配房源，可以考虑以下单项放宽（原条件尚未修改）：", "There are currently no strict matches to display. You could consider these single-condition relaxations; your original criteria have not changed:")]
    for suggestion in relaxations:
        separator = "；" if language == "zh" else "; "
        lines.append(f"- {_relaxation_change(suggestion, language)}{separator}{_relaxation_count_text(suggestion, language)}")
    return "\n".join(lines)


def _relaxation_count_text(suggestion: RelaxationSuggestion, language: ResponseLanguage) -> str:
    count = suggestion["match_count"]
    summary = suggestion.get("check_summary")
    if not summary:
        return _text(language, f"数据库匹配 {count} 套，尚未进行 URL 检查。", f"The database matched {count} listings; their URLs have not been checked.")
    return _text(
        language,
        f"本次校验后可展示 {count} 套。{_check_summary_text(summary, language)}",
        f"{count} listings can be displayed from this check. {_check_summary_text(summary, language)}",
    )


def _check_summary_text(summary: ListingCheckSummary, language: ResponseLanguage) -> str:
    text = _text(
        language,
        f"本次数据库筛选 {summary['database_match_count']} 套；已检查 {summary['checked_count']} 套（含有效期内缓存）：原链接有效 {summary['active_count']} 套、状态无法确认 {summary['unknown_count']} 套、原链接失效 {summary['inactive_count']} 套。",
        f"The database matched {summary['database_match_count']} candidates; {summary['checked_count']} were checked, including fresh cached checks: {summary['active_count']} active original links, {summary['unknown_count']} unverified links, and {summary['inactive_count']} inactive original links.",
    )
    if summary["unchecked_count"]:
        text += _text(
            language,
            f"另有 {summary['unchecked_count']} 套尚未检查，本次可展示数不代表全部匹配数。",
            f"Another {summary['unchecked_count']} candidates remain unchecked; the displayable count is not the total matching count.",
        )
    if summary["active_count"] or summary["unknown_count"]:
        text += _text(language, "链接检查不代表已确认房源仍可租。", "Link checks do not confirm that a listing is still available to rent.")
    return text


def _relaxation_change(suggestion: RelaxationSuggestion, language: ResponseLanguage) -> str:
    field = suggestion["field"]
    if field == "max_price_sgd":
        return _text(language, f"将最高预算从 S${suggestion['current']:,} 提高到 S${suggestion['suggested']:,}", f"raising the maximum budget from S${suggestion['current']:,} to S${suggestion['suggested']:,}")
    if field == "max_mrt_minutes":
        return _text(language, f"将 MRT 步行上限从 {suggestion['current']} 分钟放宽到 {suggestion['suggested']} 分钟", f"increasing the MRT walking limit from {suggestion['current']} to {suggestion['suggested']} minutes")
    return _text(language, f"调整 {field}", f"changing {field}")


_NEARBY_COUNTS = {
    "zh": (("poi_fnb_1km", "餐饮 {} 处"), ("poi_hawker_1km", "小贩中心 {} 个"), ("poi_healthcare_1km", "医疗 {} 处"), ("poi_library_1km", "图书馆 {} 个"), ("poi_sport_1km", "体育设施 {} 处"), ("poi_community_1km", "民众俱乐部 {} 个")),
    "en": (("poi_fnb_1km", "{} F&B"), ("poi_hawker_1km", "{} hawker centres"), ("poi_healthcare_1km", "{} healthcare"), ("poi_library_1km", "{} libraries"), ("poi_sport_1km", "{} sports facilities"), ("poi_community_1km", "{} community clubs")),
}


def _nearby_text(listing: Listing, language: ResponseLanguage) -> str:
    """V2 counts sit within 1 km in a straight line; the school walk is a route."""
    counts = [text.format(listing[field]) for field, text in _NEARBY_COUNTS[language] if listing.get(field)]
    school = listing.get("pg_school_nearest_walk_m")
    if not counts:
        return ""
    joined = ("、" if language == "zh" else ", ").join(counts)
    line = _text(language, f"- 周边（直线 1 公里内）：{joined}", f"- Nearby (within 1 km, straight line): {joined}")
    if school is not None:
        line += _text(language, f"；最近学校步行 {school:,.0f} 米", f"; nearest school {school:,.0f} m on foot")
    return line


def _availability_text(listing: Listing, language: ResponseLanguage) -> str:
    status = listing.get("availability_status") or "unknown"
    return _AVAILABILITY_TEXT[language].get(status, str(status))


def _warning_text(
    flag: str,
    language: ResponseLanguage,
    listing: Listing | None = None,
) -> str:
    if flag == "live_status_unknown" and listing:
        return _link_status_text(listing, language)
    return _WARNING_TEXT[language].get(flag, flag)


def _link_status_text(listing: Listing, language: ResponseLanguage) -> str:
    status = listing.get("live_status") or "unknown"
    if status == "active":
        return _text(language, "有效", "active")
    if status == "inactive":
        return _text(language, "原链接已失效", "the original link is inactive")

    reason = str(listing.get("live_error_reason") or "")
    if reason.startswith("http_"):
        cause = _text(language, f"网站返回 HTTP {reason[5:]}", f"the website returned HTTP {reason[5:]}")
    else:
        cause = {
            "network_error": _text(language, "检查时发生网络错误", "a network error interrupted the check"),
            "timeout": _text(language, "链接检查超时", "the link check timed out"),
            "checker_error": _text(language, "链接检查程序出错", "the link checker failed"),
            "listing_id_not_found": _text(language, "页面响应中无法确认房源编号", "the listing ID could not be confirmed from the response"),
        }.get(reason, _text(language, "自动检查没有得到确定结果", "the automated check was inconclusive"))
    return _text(
        language,
        f"{cause}，因此暂时无法确认链接是否仍然有效；这不表示房源已下架",
        f"{cause}, so the link cannot currently be verified; this does not mean the listing is inactive",
    )


def _display(value: object, missing: str) -> str:
    return str(value).replace("_", " ") if value not in {None, "unknown"} else missing


def _text(language: ResponseLanguage, zh: str, en: str) -> str:
    return en if language == "en" else zh
