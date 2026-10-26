import streamlit as st
from data.demo_enrichment import DEMO
from data.image_loader import source_image
from domain.provenance import display
from content.i18n import t, lease_term_label
from state.session_store import toggle_favorite, toggle_compare, favorite_ids, compare_ids, live, current, current_faculty, busy, faculties
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
    """The trips to the user's faculty and to the conversation's other destination, from the backend's
    commute data; the demo estimate offline."""
    if not live():
        commute = DEMO.get(listing.id, {}).get('commute')
        return t(f'Estimated demo commute: {commute} min', f'演示通勤估计：{commute} 分钟') if commute is not None else t('NUS commute: Not available', 'NUS 通勤：无数据')
    faculty = current_faculty()
    if faculty is None:
        text = t('Choose your faculty in Profile to see commute times.', '在个人资料里选择学院后可以看到通勤时间。')
    else:
        text = _trip_text((listing.facts.get('commutes') or {}).get(faculty['name']), t(faculty['name'], faculty['zh']))
    if other := other_commute_text(listing, rec):
        text += t('; ', '；') + other
    return text


def other_commute_text(listing, rec=None):
    """The trip to the other destination (a roommate's faculty, a gym) the conversation names; '' without one."""
    destination = (current().get('criteria') or {}).get('preferences', {}).get('other_destination')
    if not destination:
        return ''
    trip = rec.facts.get('other_commute') if rec else None
    if trip is None and destination.get('faculty'):
        trip = (listing.facts.get('commutes') or {}).get(destination['faculty'])
    elif trip is None and destination.get('latitude') is not None:
        # Routes to a place are filed by its position, as the backend's place_key does.
        trip = (listing.facts.get('place_commutes') or {}).get(f"{destination['latitude']:.5f},{destination['longitude']:.5f}")
    return _trip_text(trip, destination_text(destination))


def destination_text(destination):
    """The other destination as cards name it: what it is to the user, then the faculty or place."""
    faculty = next((item for item in faculties() if item['name'] == destination.get('faculty')), None)
    place = t(faculty['name'], faculty['zh']) if faculty else destination['query']
    name = destination.get('name')
    return t(f'{name} ({place})', f'{name}（{place}）') if name else place


def _trip_text(trip, place):
    if not trip or trip.get('minutes') is None:
        return t(f'No commute time to {place} for this listing.', f'这套房源没有到{place}的通勤数据。')
    minutes = round(trip['minutes'])
    if trip.get('mode') == 'walk':
        return t(f'About {minutes} min walk to {place}', f'步行到{place}约 {minutes} 分钟')
    return t(f'About {minutes} min by public transport to {place}', f'坐公共交通到{place}约 {minutes} 分钟')


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



def image(listing, width=500):
    """The listing's first photo, fetched by the server, which shows a placeholder when it fails."""
    content = source_image(listing.images[0]) if listing.images else None
    if content and live():
        st.image(content, width=width)
        # The photos are PropertyGuru's: say so, with the way to the original listing.
        st.caption(f"[{t('Photo from the original PropertyGuru listing', '图片来自 PropertyGuru 原房源')} ↗]({listing.facts['listingUrl']})")
    elif content:
        st.image(
            content,
            width=width,
            caption=t(
                'Historical V1 source listing image',
                '历史 V1 来源图片'
            )
        )
    else:
        st.info(
            t(
                'Listing image unavailable. View the original listing for photos.',
                '没有图片，可以打开原链接查看。'
            ),
            icon=':material/image:'
        )

def box_label(comparing):
    """With the backend, the compare button puts the listing in the compare box or takes it out."""
    return t('Remove from compare', '移出比较框') if comparing else t('Add to compare', '放进比较框')


def box_help(comparing):
    return (t('Take this listing out of the compare box', '把这套房源从比较框里拿出来') if comparing
            else t('Put this listing in the compare box (up to 3). Nothing is compared until you press Compare, in the Compare bar on Home or on Favorites.',
                   '放进比较框（最多 3 套）。在首页的比较栏或收藏页按“开始比较”才会比较。'))


def actions(listing, key):
    a,b,c = st.columns(3)
    a.link_button(t('Open ↗', '打开 ↗'), listing.facts['listingUrl'], help=t('Open the original listing in a new tab', '在新标签页打开原始房源'), width='stretch')
    saved = listing.id in favorite_ids()
    save_help = t('Remove this listing from Favorites', '从收藏夹移除这套房源') if saved else t('Save this listing to view it in Favorites', '收藏这套房源，可在收藏夹中查看')
    if b.button(t('Unsave', '取消收藏') if saved else t('Save', '收藏'), key=f'save-{key}', help=save_help, width='stretch'):
        toggle_favorite(listing.id)
        st.rerun()
    comparing = listing.id in compare_ids()
    if live():
        compare_label, compare_help = box_label(comparing), box_help(comparing)
    else:
        compare_label = t('Remove compare', '移出比较') if comparing else t('Compare', '比较')
        compare_help = t('Remove this listing from the comparison table in Favorites', '从收藏夹的对比表中移除这套房源') if comparing else t('Add to the comparison table in Favorites (up to 3 listings; no need to save first)', '加入收藏夹中的对比表（最多 3 套，无需先收藏）')
    # The compare box waits while the agent is still replying.
    if c.button(compare_label, key=f'compare-{key}', help=compare_help, width='stretch', disabled=live() and busy(current())):
        toggle_compare(listing.id)
        st.rerun()

def card(listing, rec, key, more=None):
    """more: drawn at the end inside the card, such as the folded full details on Favorites."""
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
        if more:
            more()
