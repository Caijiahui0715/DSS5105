import streamlit as st
from data.demo_enrichment import DEMO
from data.image_loader import source_image
from domain.provenance import display
from content.i18n import t, lease_term_label
from state.session_store import toggle_favorite, toggle_compare, favorite_ids, live, current_faculty
from components.source_notes import source_notes


def status_label(status):
    return {'pass':t('Meets your conditions', '符合条件'), 'needs_confirmation':t('Needs confirmation', '待确认'), 'fail':t('Fail', '不符合')}[status]


def heading(rec):
    """Rank and status; for the agent's listings, which of your conditions the listing does not state."""
    if rec is None:
        st.caption(t('Not in the latest search results', '不在最近一次的搜索结果里'))
        return
    demo = t(' · Demo recommendation', ' · 演示推荐') if rec.is_demo_score else ''
    st.caption(f'#{rec.rank} · {status_label(rec.evaluation.status)}{demo}')
    if not rec.is_demo_score and rec.unknown_factors:
        st.caption(t('To confirm with the landlord: ', '需要向房东确认：') + ', '.join(rec.unknown_factors))


def commute_text(listing, rec=None):
    """The trip to the user's faculty from the backend's commute data; the demo estimate offline."""
    if not live():
        commute = DEMO.get(listing.id, {}).get('commute')
        return t(f'Estimated demo commute: {commute} min', f'演示通勤估计：{commute} 分钟') if commute is not None else t('NUS commute: Not available', 'NUS 通勤：无数据')
    faculty = current_faculty()
    if faculty is None:
        return t('Choose your faculty in Profile to see commute times.', '在个人资料里选择学院后可以看到通勤时间。')
    name, zh = faculty['name'], faculty['zh']
    trip = (listing.facts.get('commutes') or {}).get(name)
    if not trip or trip.get('minutes') is None:
        return t(f'No commute time to {name} for this listing.', f'这套房源没有到{zh}的通勤数据。')
    minutes = round(trip['minutes'])
    if trip.get('mode') == 'walk':
        return t(f'About {minutes} min walk to {name}', f'步行到{zh}约 {minutes} 分钟')
    return t(f'About {minutes} min by public transport to {name}', f'坐公共交通到{zh}约 {minutes} 分钟')


def mrt_text(listing, rec=None):
    f = listing.facts
    facts = rec.facts if rec else {}
    minutes, distance = facts.get('mrt_minutes'), f.get('mrtDistanceM')
    detail = t(f' · {minutes} min walk', f' · 步行 {minutes} 分钟') if minutes is not None else t(f' · {distance:,.0f} m', f' · {distance:,.0f} 米') if distance is not None else ''
    return f"MRT: {display(f['mrtStation'])}{detail}"


def lease_text(listing):
    """The advert's lease term: the shortest lease the landlord accepts."""
    return t('Lease: ', '租期：') + lease_term_label(listing.facts.get('leaseTerm'))


def link_note(rec):
    note = rec and rec.facts.get('link_note')
    if note:
        st.caption(t('Original link: ', '原链接：') + note)


def image(listing):
    content = source_image(listing.images[0]) if listing.images else None
    if content:
        st.image(content, width='stretch', caption=t('Historical V1 source listing image', '历史 V1 来源图片'))
    else:
        st.info(t('Listing image unavailable. View the original listing for photos.', '没有图片，可以打开原链接查看。'), icon=':material/image:')

def actions(listing, key):
    a,b,c = st.columns(3)
    if a.button(t('Details', '详情'), key=f'details-{key}', width='stretch'):
        st.session_state.selected_listing = listing.id
        st.rerun()
    saved = listing.id in favorite_ids()
    if b.button(t('Unsave', '取消收藏') if saved else t('Save', '收藏'), key=f'save-{key}', width='stretch'):
        toggle_favorite(listing.id)
        st.rerun()
    if c.button(t('Remove compare', '移出比较') if listing.id in st.session_state.compare else t('Compare', '比较'), key=f'compare-{key}', width='stretch'):
        toggle_compare(listing.id)
        st.rerun()

def card(listing, rec, key):
    f = listing.facts
    with st.container(border=True):
        heading(rec)
        st.subheader(f['displayTitle'])
        if listing.provenance['displayTitle'] == 'derived':
            st.caption(t('English source-title excerpt · Derived display', '英文标题摘录 · 派生显示'))
        st.markdown(t(f"### SGD {f['effectiveRentMonthlySgd']:,.0f} / month", f"### 每月 {f['effectiveRentMonthlySgd']:,.0f} 新元"))
        source_notes(listing)
        image(listing)
        st.write(f"{display(f['propertyType'])} · {display(f['roomType'])} · {f['districtCode']}")
        st.caption(f['address'])
        if rec is not None and rec.score is not None:
            st.write(f"**{rec.score} / 100** — {rec.match_level}")
            st.caption(t('Demo match score · unknown factors reduce evidence coverage', '演示匹配分 · 未知因素会降低证据覆盖'))
        st.write(mrt_text(listing, rec))
        st.caption(commute_text(listing, rec))
        st.caption(lease_text(listing))
        for reason in (rec.reasons[:2] if rec else []):
            st.write(f'✓ {reason}')
        if rec and rec.tradeoffs:
            st.caption(rec.tradeoffs[0])
        link_note(rec)
        if listing.metadata['reviewFlags']:
            st.warning(t('Data needs review', '数据需要核实'), icon=':material/info:')
        actions(listing, key)
        if st.button(t('View on map', '在地图上查看'), key=f'view-map-{key}'):
            st.session_state.selected_listing = listing.id
            st.session_state.page = 'Home'
            st.rerun()
        st.link_button(t('View original listing', '打开原链接'), f['listingUrl'])
