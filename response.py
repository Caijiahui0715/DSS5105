from models import (
    Listing,
    RankingResult,
    RelaxationSuggestion,
    ResponseLanguage,
    RestrictionSummary,
    UserIntent,
)


_FACTOR_LABELS = {
    "zh": {"price": "价格", "mrt": "MRT"},
    "en": {"price": "price", "mrt": "MRT"},
}

_RESTRICTION_TEXT = {
    "zh": {
        ("cooking", "allowed"): "允许做饭",
        ("cooking", "limited"): "仅允许有限做饭",
        ("cooking", "not_allowed"): "不允许做饭",
        ("owner_staying", "yes"): "房东同住",
        ("owner_staying", "no"): "房东不同住",
        ("tenant_gender", "female_only"): "仅限女性租客",
        ("tenant_gender", "male_preferred"): "偏好男性租客",
        ("visitors", "not_allowed"): "不允许访客",
        ("smoking", "not_allowed"): "禁止吸烟",
    },
    "en": {
        ("cooking", "allowed"): "cooking allowed",
        ("cooking", "limited"): "limited cooking only",
        ("cooking", "not_allowed"): "no cooking",
        ("owner_staying", "yes"): "owner staying",
        ("owner_staying", "no"): "owner not staying",
        ("tenant_gender", "female_only"): "female tenants only",
        ("tenant_gender", "male_preferred"): "male tenant preferred",
        ("visitors", "not_allowed"): "no visitors",
        ("smoking", "not_allowed"): "no smoking",
    },
}


def render_response(
    ranked_listings: list[RankingResult] | None = None,
    restrictions: dict[str, RestrictionSummary] | None = None,
    relaxations: list[RelaxationSuggestion] | None = None,
    *,
    heading: str | None = None,
    limit: int = 3,
    language: ResponseLanguage = "zh",
) -> str:
    ranked_listings = ranked_listings or []
    restrictions = restrictions or {}
    if not ranked_listings:
        return _render_relaxations(relaxations or [], language)

    lines = [
        heading
        or _text(
            language,
            f"找到 {len(ranked_listings)} 套符合条件的房源，以下按匹配度排序：",
            f"Found {len(ranked_listings)} matching listings, ranked by fit:",
        )
    ]
    for index, item in enumerate(ranked_listings[:limit], 1):
        listing = item["listing"]
        listing_id = listing["listing_id"]
        price = listing.get("price_sgd")
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

        if listing.get("availability_text"):
            lines.append(
                _text(
                    language,
                    f"   入住时间：{listing['availability_text']}",
                    f"   Availability: {listing['availability_text']}",
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
        if item.get("warnings"):
            lines.append(
                _text(
                    language,
                    f"   数据提示：{', '.join(item['warnings'])}",
                    f"   Data notes: {', '.join(item['warnings'])}",
                )
            )

    return "\n".join(lines)


def render_intent_response(
    intent: UserIntent,
    ranked_listings: list[RankingResult] | None = None,
    restrictions: dict[str, RestrictionSummary] | None = None,
    relaxations: list[RelaxationSuggestion] | None = None,
    language: ResponseLanguage = "zh",
) -> str:
    if intent == "show_results":
        if ranked_listings:
            return render_response(ranked_listings, restrictions, language=language)
        if relaxations:
            suggestion = relaxations[0]
            return (
                _text(
                    language,
                    f"目前没有严格符合条件的房源。是否接受{_relaxation_change(suggestion, language)}？"
                    f"接受后预计可找到 {suggestion['match_count']} 套房源。",
                    f"No listings meet every condition. Would you accept "
                    f"{_relaxation_change(suggestion, language)}? This should find "
                    f"about {suggestion['match_count']} listings.",
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
        if isinstance(listing.get("price_sgd"), (int, float))
    ]
    if priced:
        cheapest = min(priced, key=lambda listing: listing["price_sgd"])
        lines.append(
            _text(
                language,
                f"- 最低月租：{cheapest['listing_id']}（S${cheapest['price_sgd']:,}）",
                f"- Lowest rent: {cheapest['listing_id']} (S${cheapest['price_sgd']:,})",
            )
        )

    with_mrt = [
        (listing, _mrt_minutes(listing))
        for listing in listings
        if _mrt_minutes(listing) is not None
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
    price = listing.get("price_sgd")
    verified = listing.get("platform_verified")
    lines = [
        _text(language, f"房源详情：{listing.get('title') or '未命名房源'}（{listing['listing_id']}）", f"Listing details: {listing.get('title') or 'Untitled listing'} ({listing['listing_id']})"),
        _text(language, f"- 月租：{f'S${price:,}' if isinstance(price, (int, float)) else '未知'}", f"- Monthly rent: {f'S${price:,}' if isinstance(price, (int, float)) else 'unknown'}"),
        _text(language, f"- 房型：{listing.get('room_type') or '未知'}", f"- Room type: {listing.get('room_type') or 'unknown'}"),
        _text(language, f"- 地区：{listing.get('district_code') or '未知'}", f"- District: {listing.get('district_code') or 'unknown'}"),
        _text(language, f"- 地址：{listing.get('address') or '未知'}", f"- Address: {listing.get('address') or 'unknown'}"),
        _text(language, f"- MRT：{listing.get('mrt_station') or '车站未知'}，{_mrt_text(listing, language)}", f"- MRT: {listing.get('mrt_station') or 'unknown station'}, {_mrt_text(listing, language)}"),
        _text(language, f"- 入住时间：{listing.get('availability_text') or '未知'}", f"- Availability: {listing.get('availability_text') or 'unknown'}"),
        _text(language, f"- 平台认证：{'是' if verified is True else '否' if verified is False else '未知'}", f"- Platform verified: {'yes' if verified is True else 'no' if verified is False else 'unknown'}"),
    ]
    rules = [
        text
        for key, value in restrictions.items()
        if (text := _RESTRICTION_TEXT[language].get((key, value)))
    ]
    if rules:
        lines.append(_text(language, f"- 居住条件：{'；'.join(rules)}", f"- Conditions: {'; '.join(rules)}"))
    if listing.get("review_flags"):
        lines.append(_text(language, f"- 数据提示：{', '.join(listing['review_flags'])}", f"- Data notes: {', '.join(listing['review_flags'])}"))
    return "\n".join(lines)


def render_relaxation_preview(
    suggestion: RelaxationSuggestion,
    ranked_listings: list[RankingResult],
    restrictions: dict[str, RestrictionSummary],
    language: ResponseLanguage = "zh",
) -> str:
    if not ranked_listings:
        return _text(language, "该让步条件下暂时没有可展示的房源，请重新搜索。", "There are no listings to preview under that relaxation. Please search again.")
    return _text(
        language,
        f"按“{_relaxation_change(suggestion, language)}”预览，尚未修改你的原搜索条件：\n\n"
        f"{render_response(ranked_listings, restrictions, language=language)}",
        f"Previewing results after {_relaxation_change(suggestion, language)}; your original search criteria have not changed:\n\n"
        f"{render_response(ranked_listings, restrictions, language=language)}",
    )


def _mrt_text(listing: dict, language: ResponseLanguage) -> str:
    minutes = _mrt_minutes(listing)
    if listing.get("mrt_walk_minutes") is not None:
        distance = listing.get("mrt_walk_distance_m")
        suffix = _text(language, f"（{distance:,} 米）", f" ({distance:,} m)") if isinstance(distance, (int, float)) else ""
        return _text(language, f"OneMap 步行约 {minutes} 分钟{suffix}", f"about {minutes} minutes on foot via OneMap{suffix}")

    return _text(language, f"房源描述约 {minutes} 分钟", f"about {minutes} minutes according to the listing") if minutes is not None else _text(language, "时间未知", "walking time unknown")


def _mrt_minutes(listing: dict) -> int | float | None:
    walked = listing.get("mrt_walk_minutes")
    return walked if walked is not None else listing.get("mrt_minutes_reported")


def _render_relaxations(relaxations: list[RelaxationSuggestion], language: ResponseLanguage) -> str:
    if not relaxations:
        return _text(language, "没有找到完全符合条件的房源，也没有发现单项小幅放宽即可得到结果。", "No listings meet every condition, and no single small relaxation produced a match.")

    lines = [_text(language, "没有找到完全符合条件的房源，可以考虑：", "No listings meet every condition. You could consider:")]
    for suggestion in relaxations:
        count = suggestion["match_count"]
        lines.append(_text(language, f"- {_relaxation_change(suggestion, language)}，预计可找到 {count} 套房源", f"- {_relaxation_change(suggestion, language)}; this should find about {count} listings"))
    return "\n".join(lines)


def _relaxation_change(suggestion: RelaxationSuggestion, language: ResponseLanguage) -> str:
    field = suggestion["field"]
    if field == "max_price_sgd":
        return _text(language, f"将最高预算从 S${suggestion['current']:,} 提高到 S${suggestion['suggested']:,}", f"raising the maximum budget from S${suggestion['current']:,} to S${suggestion['suggested']:,}")
    if field == "max_mrt_minutes":
        return _text(language, f"将 MRT 步行上限从 {suggestion['current']} 分钟放宽到 {suggestion['suggested']} 分钟", f"increasing the MRT walking limit from {suggestion['current']} to {suggestion['suggested']} minutes")
    if field == "verified_only":
        return _text(language, "取消“仅认证房源”限制", "including unverified listings")
    return _text(language, f"调整 {field}", f"changing {field}")


def _text(language: ResponseLanguage, zh: str, en: str) -> str:
    return en if language == "en" else zh
