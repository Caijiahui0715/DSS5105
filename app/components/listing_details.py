import streamlit as st
import json
import re
from components.listing_card import image, actions, heading, commute_text, mrt_text, link_note
from components.provenance_badge import fact, explanation
from content.i18n import t
from domain.location import coordinates, location_note
from domain.provenance import display
from components.source_notes import source_notes

def details(listing, recommendation=None, key='detail'):
    if listing is None:
        st.info(t('Select a listing card, map marker, or the listing selector to explore details.', '选择一张房源卡片、地图标记或列表中的房源查看详情。'))
        return
    f = listing.facts
    st.subheader(f['displayTitle'])
    if listing.provenance['displayTitle'] == 'derived':
        st.caption(t('Derived display: English excerpt from the original bilingual title. Original source record is unchanged.', '派生显示：取自原双语标题的英文部分，原始记录未改动。'))
    image(listing)
    fact(t('Latest recorded monthly rent (SGD)', '最新记录的月租（新元）'), f['effectiveRentMonthlySgd'])
    fact(t('Original advertised monthly rent (SGD)', '原广告月租（新元）'), f['rentMonthlySgd'])
    source_notes(listing)
    fact(t('Price type', '价格类型'), f['rentPriceType'])
    st.caption(t('This is not a confirmed total monthly housing cost.', '这不是确认过的每月住房总费用。'))
    if recommendation:
        heading(recommendation)
        if recommendation.score is not None:
            st.write(t(f'**Demo match score: {recommendation.score} / 100** — {recommendation.match_level}', f'**演示匹配分：{recommendation.score} / 100** — {recommendation.match_level}'))
            with st.expander(t('Why it matches, trade-offs and unknowns', '匹配原因、取舍和未知因素')):
                for reason in recommendation.reasons:
                    st.write(f'✓ {reason}')
                for tradeoff in recommendation.tradeoffs:
                    st.write(f'• {tradeoff}')
                st.write(t('Unknown factors:', '未知因素：'), ', '.join(recommendation.unknown_factors))
                st.write(t('Demo score components (0–1; missing = no points):', '演示分构成（0–1；缺失记 0 分）：'))
                st.json(recommendation.breakdown)
                st.json(recommendation.evaluation.checks)
        link_note(recommendation)
    with st.expander(t('Property and location', '房屋和位置'), expanded=True):
        for label, field in [(t('Rental scope', '租住方式'),'rentalScope'),(t('Property type', '房产类型'),'propertyType'),(t('Room type', '房间类型'),'roomType'),(t('Bedrooms', '卧室'),'bedrooms'),(t('Bathrooms', '浴室'),'bathrooms'),(t('Area (sqm)', '面积（平方米）'),'areaSqm'),(t('Area scope', '面积口径'),'areaScope'),(t('District', '区'),'districtName'),(t('Address', '地址'),'address'),(t('Advertised MRT', '广告标注的地铁站'),'mrtStation'),(t('MRT distance (m)', '到地铁站距离（米）'),'mrtDistanceM'),(t('Reported MRT minutes', '广告标注的步行分钟'),'mrtMinutesReported'),(t('MRT operation status', '地铁站运营状态'),'mrtOperationStatus')]:
            fact(label, f[field], listing.provenance[field])
        st.caption(t('Bathroom count does not imply private use. Advertised MRT minutes are not NUS commute time; station operation may be unknown.', '浴室数量不代表独用。广告标注的地铁步行时间不是到 NUS 的通勤时间；地铁站是否运营可能未知。'))
        st.markdown(f"**{t('Commute', '通勤')}**")
        st.write(commute_text(listing, recommendation))
        fact(t('Data map coordinates', '数据中的地图坐标'), coordinates(listing), listing.provenance['coordinates'])
        st.caption(location_note(listing))
        fact(t('Postcode', '邮编'), f.get('postcode'))
        fact(t('Street', '街道'), f.get('streetName'))
    with st.expander(t('Furnishing and lifestyle', '家具和生活')):
        for label, field in [(t('Furnishing', '家具'),'furnishing'),(t('Private bathroom', '独立卫浴'),'privateBathroom'),(t('Cooking', '做饭'),'cookingPolicy'),(t('Air conditioning', '空调'),'airConditioning'),(t('Landlord lives in', '房东同住'),'landlordLivesIn'),(t('Pets policy', '宠物政策'),'petsPolicy'),(t('Reported tenant count', '广告标注的租客数'),'tenantCountReported'),(t('Platform gender label', '平台性别标签'),'tenantGenderLabel'),(t('Explicit gender restriction', '明确的性别限制'),'genderRestriction'),(t('Gender preference', '性别偏好'),'genderPreference')]:
            fact(label, f[field], listing.provenance[field])
        st.caption(t('Tenant count is not confirmed occupancy capacity. Platform labels are not verified roommate information; preferences are not exclusion rules.', '租客数不是确认过的可住人数。平台标签不是核实过的室友信息；偏好不等于排除规则。'))
    with st.expander(t('Availability, review and provenance', '可租状态、核实和数据来源')):
        fact(t('V2 snapshot link status', 'V2 快照时的链接状态'), f.get('scrapeStatus'))
        fact(t('V2 last checked', 'V2 最近检查时间'), f.get('enrichedAt'))
        fact(t('Historical V1 availability status', '历史 V1 可租状态'), listing.metadata['availabilityStatus'])
        fact(t('Historical V1 availability text', '历史 V1 可租说明'), listing.evidence['availabilityText'])
        st.warning(t('Listing availability has not been verified in real time.', '房源是否还能租没有实时核实。'))
        fact(t('Listed date', '发布日期'), f['listedDate'])
        fact(t('Collected at (timezone unconfirmed)', '采集时间（时区未确认）'), f['collectedAt'])
        if listing.metadata['reviewFlags']:
            st.write(t('Data needs review:', '数据需要核实：'), ', '.join(listing.metadata['reviewFlags']))
        else:
            st.caption(t('No recorded flags. This does not mean every fact has been verified.', '没有记录到问题，但不代表每项信息都核实过。'))
        st.caption(t('Review flags identify checks to make; they do not prove an error.', '核实标记只是提示要检查的地方，不代表一定有错。'))
        explanation()
        st.json(listing.provenance)
        st.write(t('Original V2 categorical labels (before UI normalization):', 'V2 原始分类标签（界面统一前）：'))
        st.json({field: listing.source_fields.get(field) for field in ('cooking_policy', 'pets_policy')})
        st.write(t('Source card text:', '来源卡片文字：'))
        text = listing.evidence.get('cardText') or t('Not provided', '未提供')
        if re.search('[㐀-鿿]',text):
            st.caption(t('The original advertisement includes non-English text. Use the original listing link to inspect it; the source record has been preserved without translation.', '原广告含非英文内容，请打开原链接查看；来源记录未经翻译。'))
        else:
            st.text(text)
        with st.expander(t('Source extraction evidence', '字段提取依据')):
            evidence = {k:v for k,v in listing.evidence.items() if k in ('fieldEvidence','ruleEvidence')}
            if re.search('[㐀-鿿]',json.dumps(evidence,ensure_ascii=False)):
                st.caption(t('Non-English source evidence remains in the supplied evidence file. It is not translated or reproduced here.', '非英文的来源依据保留在原文件里，这里不翻译也不转载。'))
            else:
                st.json(evidence)
    actions(listing, key)
    st.link_button(t('View original listing', '打开原链接'), f['listingUrl'], width='stretch')
    st.caption(t('Historical source links may be unavailable or changed.', '历史来源链接可能已失效或变更。'))


def compact_details(listing, recommendation):
    """Small source-grounded card inside the fixed Home detail panel."""
    if listing is None:
        st.info(t('This listing is no longer in the data.', '这套房源已不在当前数据里。'))
        return
    f = listing.facts
    st.subheader(f['displayTitle'])
    if listing.provenance['displayTitle'] == 'derived':
        st.caption(t('English source-title excerpt · Derived display', '英文标题摘录 · 派生显示'))
    st.markdown(t(f"**SGD {f['effectiveRentMonthlySgd']:,.0f} / month** · {display(f['rentPriceType'])}", f"**每月 {f['effectiveRentMonthlySgd']:,.0f} 新元** · {display(f['rentPriceType'])}"))
    source_notes(listing)
    st.write(f"{display(f['propertyType'])} · {display(f['rentalScope'])}")
    st.caption(f"{f['districtCode']} · {f['address']}")
    heading(recommendation)
    if recommendation.score is not None:
        st.write(t(f"**{recommendation.score} / 100** · Demo match score", f"**{recommendation.score} / 100** · 演示匹配分"))
    st.caption(mrt_text(listing, recommendation))
    st.caption(commute_text(listing, recommendation))
    link_note(recommendation)
    if listing.metadata['reviewFlags']:
        st.caption(t('Data needs review', '数据需要核实'))
    for reason in recommendation.reasons[:2]:
        st.caption(reason)
    actions(listing, 'home-selected')
    with st.expander(t('Listing facts and provenance', '房源信息和来源')):
        fact(t('Original advertised monthly rent (SGD)', '原广告月租（新元）'), f['rentMonthlySgd'])
        fact(t('Refreshed advertised monthly rent (SGD)', '重新检查后的广告月租（新元）'), f.get('rentMonthlySgdNow'))
        for label, field in [(t('Room type', '房间类型'),'roomType'), (t('Bedrooms', '卧室'),'bedrooms'), (t('Bathrooms', '浴室'),'bathrooms'), (t('Area (sqm)', '面积（平方米）'),'areaSqm'), (t('Area scope', '面积口径'),'areaScope'), (t('MRT distance (m)', '到地铁站距离（米）'),'mrtDistanceM'), (t('Reported MRT minutes', '广告标注的步行分钟'),'mrtMinutesReported'), (t('Furnishing', '家具'),'furnishing'), (t('Private bathroom', '独立卫浴'),'privateBathroom'), (t('Cooking', '做饭'),'cookingPolicy'), (t('Air conditioning', '空调'),'airConditioning'), (t('Pets', '宠物'),'petsPolicy')]:
            fact(label, f[field], listing.provenance[field])
        fact(t('V2 snapshot link status', 'V2 快照时的链接状态'), f.get('scrapeStatus'))
        fact(t('Data map coordinates', '数据中的地图坐标'), coordinates(listing), listing.provenance['coordinates'])
        st.caption(location_note(listing))
        fact(t('Historical V1 availability', '历史 V1 可租状态'), listing.metadata['availabilityStatus'])
        st.caption(t('Listing availability has not been verified in real time.', '房源是否还能租没有实时核实。'))
        st.caption(t('Bathrooms do not imply private use; reported MRT minutes are not NUS commute.', '浴室数量不代表独用；广告标注的地铁步行时间不是到 NUS 的通勤时间。'))
        if recommendation.tradeoffs:
            st.write(t('Trade-offs:', '取舍：'), ' · '.join(recommendation.tradeoffs))
        explanation()
    st.link_button(t('View original listing', '打开原链接'), f['listingUrl'])
