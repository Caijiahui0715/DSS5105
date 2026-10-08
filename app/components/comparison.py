import pandas as pd
import streamlit as st
from components.listing_card import status_label, commute_text
from content.i18n import t
from domain.provenance import display

def comparison(api, recommendations):
    ids = st.session_state.compare
    if not ids:
        st.info(t('Use Compare on a listing to compare up to three options.', '在房源上点“比较”，最多可以比较三套。'))
        return
    st.subheader(t(f'Compare {len(ids)} listings', f'比较 {len(ids)} 套房源'))
    index = {rec.listing_id:rec for rec in recommendations}
    rows = {}
    for listing_id in ids[:3]:
        listing = api.details(listing_id)
        if listing is None:
            st.warning(t(f'Listing {listing_id} is outside the current active snapshot and cannot be compared.', f'房源 {listing_id} 已不在当前数据里，无法比较。'))
            continue
        f = listing.facts
        rec = index.get(listing_id)
        values = {label:display(f[field]) for label,field in [(t('Latest recorded rent (SGD)', '最新记录的月租（新元）'),'effectiveRentMonthlySgd'),(t('Original advertised rent (SGD)', '原广告月租（新元）'),'rentMonthlySgd'),(t('Snapshot status', '快照状态'),'scrapeStatus'),(t('Last checked', '最近检查'),'enrichedAt'),(t('District', '区'),'districtName'),('MRT','mrtStation'),(t('Property type', '房产类型'),'propertyType'),(t('Rental scope', '租住方式'),'rentalScope'),(t('Room type', '房间类型'),'roomType'),(t('Bedrooms', '卧室'),'bedrooms'),(t('Bathrooms', '浴室'),'bathrooms'),(t('Area (sqm)', '面积（平方米）'),'areaSqm'),(t('Area scope', '面积口径'),'areaScope'),(t('Furnishing', '家具'),'furnishing')]}
        values[t('Rank and status', '排名和状态')] = f'#{rec.rank} · {status_label(rec.evaluation.status)}' if rec else t('Not in the latest results', '不在最近的结果里')
        if rec is not None and rec.score is not None:
            values[t('Demo match score', '演示匹配分')] = f'{rec.score}/100'
        values[t('Commute', '通勤')] = commute_text(listing, rec)
        values[t('To confirm', '待确认')] = ', '.join(rec.unknown_factors) if rec and rec.unknown_factors else '—'
        values[t('Historical V1 availability', '历史 V1 可租状态')] = display(listing.metadata['availabilityStatus'])
        if rec is not None and rec.is_demo_score:
            values[t('Demo reasons', '演示理由')] = ' | '.join(rec.reasons) or '—'
            values[t('Trade-offs', '取舍')] = ' | '.join(rec.tradeoffs) or '—'
        rows[f'{f["displayTitle"]} ({listing_id})'] = values
    st.dataframe(pd.DataFrame(rows), width='stretch')
    st.caption(t('Source facts, with commute times from the agent backend. Availability is not verified in real time.', '表中是来源数据，通勤时间来自 agent 后端。房源是否还能租没有实时核实。'))
    if st.button(t('Clear comparison', '清空比较')):
        st.session_state.compare = []
        st.rerun()
