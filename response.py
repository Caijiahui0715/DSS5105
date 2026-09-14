from models import (
    RankingResult,
    RelaxationSuggestion,
    RestrictionSummary,
    UserIntent,
)


_FACTOR_LABELS = {"price": "价格", "mrt": "MRT"}

_RESTRICTION_TEXT = {
    ("cooking", "allowed"): "允许做饭",
    ("cooking", "limited"): "仅允许有限做饭",
    ("cooking", "not_allowed"): "不允许做饭",
    ("owner_staying", "yes"): "房东同住",
    ("owner_staying", "no"): "房东不同住",
    ("tenant_gender", "female_only"): "仅限女性租客",
    ("tenant_gender", "male_preferred"): "偏好男性租客",
    ("visitors", "not_allowed"): "不允许访客",
    ("smoking", "not_allowed"): "禁止吸烟",
}

_RELAXATION_TEXT = {
    "max_price_sgd": lambda suggestion: (
        f"将最高预算从 S${suggestion['current']:,} "
        f"提高到 S${suggestion['suggested']:,}"
    ),
    "max_mrt_minutes": lambda suggestion: (
        f"将 MRT 步行上限从 {suggestion['current']} 分钟 "
        f"放宽到 {suggestion['suggested']} 分钟"
    ),
    "verified_only": lambda suggestion: "取消“仅认证房源”限制",
}


def render_response(
    ranked_listings: list[RankingResult] | None = None,
    restrictions: dict[str, RestrictionSummary] | None = None,
    relaxations: list[RelaxationSuggestion] | None = None,
    *,
    heading: str | None = None,
    limit: int = 3,
) -> str:
    ranked_listings = ranked_listings or []
    restrictions = restrictions or {}
    if not ranked_listings:
        return _render_relaxations(relaxations or [])

    lines = [
        heading or f"找到 {len(ranked_listings)} 套符合条件的房源，以下按匹配度排序："
    ]
    for index, item in enumerate(ranked_listings[:limit], 1):
        listing = item["listing"]
        listing_id = listing["listing_id"]
        price = listing.get("price_sgd")
        lines.extend(
            [
                "",
                f"{index}. {listing.get('title') or '未命名房源'}（{listing_id}）",
                f"   月租：{f'S${price:,}' if isinstance(price, (int, float)) else '未知'}",
                f"   MRT：{_mrt_text(listing)}",
            ]
        )

        factors = item.get("factors", {})
        weights = [
            f"{_FACTOR_LABELS.get(name, name)} {round(factor['weight'] * 100)}%"
            for name, factor in factors.items()
        ]
        if weights:
            lines.append(f"   排名权重：{'，'.join(weights)}")

        if listing.get("availability_text"):
            lines.append(f"   入住时间：{listing['availability_text']}")

        rules = [
            text
            for key, value in restrictions.get(listing_id, {}).items()
            if (text := _RESTRICTION_TEXT.get((key, value)))
        ]
        if rules:
            lines.append(f"   条件：{'；'.join(rules)}")
        if item.get("warnings"):
            lines.append(f"   数据提示：{', '.join(item['warnings'])}")

    return "\n".join(lines)


def render_intent_response(
    intent: UserIntent,
    ranked_listings: list[RankingResult] | None = None,
    restrictions: dict[str, RestrictionSummary] | None = None,
    relaxations: list[RelaxationSuggestion] | None = None,
) -> str:
    if intent == "show_results":
        if ranked_listings:
            return render_response(ranked_listings, restrictions)
        if relaxations:
            suggestion = relaxations[0]
            return (
                f"目前没有严格符合条件的房源。是否接受{_relaxation_change(suggestion)}？"
                f"接受后预计可找到 {suggestion['match_count']} 套房源。"
            )
        return "目前没有可展示的房源，请先告诉我你的租房要求。"
    if intent == "reject_relaxation":
        return "好的，我会保留原来的搜索条件。你可以告诉我想调整哪项要求。"
    if intent == "reject_results":
        return "目前没有已展示的房源可以排除，请先搜索或查看房源。"
    if intent == "accept_relaxation":
        return "目前没有可接受的让步建议，请告诉我想调整的搜索条件。"
    return "我还不确定你想搜索、修改条件还是查看房源，请再说明一下。"


def render_relaxation_preview(
    suggestion: RelaxationSuggestion,
    ranked_listings: list[RankingResult],
    restrictions: dict[str, RestrictionSummary],
) -> str:
    if not ranked_listings:
        return "该让步条件下暂时没有可展示的房源，请重新搜索。"
    return (
        f"按“{_relaxation_change(suggestion)}”预览，尚未修改你的原搜索条件：\n\n"
        f"{render_response(ranked_listings, restrictions)}"
    )


def _mrt_text(listing: dict) -> str:
    minutes = listing.get("mrt_walk_minutes")
    if minutes is not None:
        distance = listing.get("mrt_walk_distance_m")
        suffix = f"（{distance:,} 米）" if isinstance(distance, (int, float)) else ""
        return f"OneMap 步行约 {minutes} 分钟{suffix}"

    minutes = listing.get("mrt_minutes_reported")
    return f"房源描述约 {minutes} 分钟" if minutes is not None else "时间未知"


def _render_relaxations(relaxations: list[RelaxationSuggestion]) -> str:
    if not relaxations:
        return "没有找到完全符合条件的房源，也没有发现单项小幅放宽即可得到结果。"

    lines = ["没有找到完全符合条件的房源，可以考虑："]
    for suggestion in relaxations:
        count = suggestion["match_count"]
        lines.append(f"- {_relaxation_change(suggestion)}，预计可找到 {count} 套房源")
    return "\n".join(lines)


def _relaxation_change(suggestion: RelaxationSuggestion) -> str:
    field = suggestion["field"]
    formatter = _RELAXATION_TEXT.get(field)
    return formatter(suggestion) if formatter else f"调整 {field}"
