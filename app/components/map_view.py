import html
import folium
import streamlit as st
from streamlit_folium import st_folium
from data.demo_enrichment import NUS_POSITION
from content.i18n import t
from domain.location import coordinates
from state.session_store import live, current_faculty


def anchor():
    """The map's reference point: the user's faculty, or the illustrative NUS point."""
    faculty = current_faculty() if live() else None
    if faculty is None:
        return NUS_POSITION, t('NUS (choose your faculty in Profile)', 'NUS（可在个人资料里选择学院）') if live() else t('NUS demo campus anchor', 'NUS 演示校园锚点')
    return (faculty['latitude'], faculty['longitude']), t(faculty['name'], faculty['zh'])


def _listing_map(api, ids, compared_ids, favorite_ids, highlight, frame):
    """A folium map of the listings in ids (None for all) and the compared ones, with the faculty.
    Compared listings are numbered teal circles in the table's order; favorites are red hearts; the
    rest are houses (purple when the position is inferred); highlight is orange. frame: the
    listings to fit in view with the faculty; none keeps the view on highlight or the faculty.
    Returns (map, positions by listing ID)."""
    home, home_name = anchor()
    allowed = None if ids is None else set(ids) | set(compared_ids)
    positioned = [listing for listing in api.all_listings() if coordinates(listing) is not None and (allowed is None or listing.id in allowed)]
    positions = {listing.id: coordinates(listing) for listing in positioned}
    number = {listing_id: index for index, listing_id in enumerate(compared_ids, 1)}
    favorites = set(favorite_ids)
    map_object = folium.Map(location=positions.get(highlight, home), zoom_start=14 if highlight in positions else 12, tiles='OpenStreetMap', control_scale=True)
    framed = [positions[listing_id] for listing_id in frame if listing_id in positions]
    if framed:
        map_object.fit_bounds([*framed, home], padding=(30, 30), max_zoom=15)
    if ids is None or positioned:
        folium.Marker(home, tooltip=html.escape(home_name), icon=folium.Icon(color='darkblue', icon='graduation-cap', prefix='fa')).add_to(map_object)
    for listing in positioned:
        f = listing.facts
        chosen = highlight == listing.id
        # The tooltip starts with the ID, which a click reads; where the position comes from is not shown.
        tooltip = f'{listing.id} | {html.escape(f["displayTitle"])} | SGD {f["effectiveRentMonthlySgd"]:,.0f}'
        if listing.id in number:
            tooltip = f'{listing.id} | {t("Compared", "比较")} #{number[listing.id]} | ' + tooltip.split(' | ', 1)[1]
            # Inline styles: the map is drawn in its own frame, which the page's CSS does not reach.
            icon = folium.DivIcon(html=(
                f'<div style="width:26px;height:26px;border-radius:50%;background:#107a72;color:#fff;border:2px solid {"#d97a00" if chosen else "#ffffff"};'
                f'box-shadow:0 1px 4px rgba(20,44,67,.45);display:flex;align-items:center;justify-content:center;'
                f'font:600 14px/1 sans-serif;">{number[listing.id]}</div>'
            ), icon_size=(30, 30), icon_anchor=(15, 15))
        elif listing.id in favorites:
            icon = folium.Icon(color='orange' if chosen else 'red', icon='heart', prefix='fa')
        else:
            inferred = listing.provenance['coordinates'] == 'derived'
            icon = folium.Icon(color='orange' if chosen else 'purple' if inferred else 'blue', icon='home', prefix='fa')
        folium.Marker(positions[listing.id], tooltip=tooltip, popup=listing.id, icon=icon).add_to(map_object)
    return map_object, positions


def _clicked(result, positions):
    """The listing a click on the map chose, if any; listings sharing a position are not guessed."""
    tooltip = result.get('last_object_clicked_tooltip') if result else None
    clicked = result.get('last_object_clicked') if result else None
    candidate = str(tooltip).split(' | ')[0] if tooltip else None
    if candidate not in positions and isinstance(clicked, dict):
        matches = [listing_id for listing_id, position in positions.items() if abs(position[0]-clicked.get('lat',0)) < .00001 and abs(position[1]-clicked.get('lng',0)) < .00001]
        candidate = matches[0] if len(matches) == 1 else None
    return (candidate if candidate in positions else None), str((candidate, clicked))


def map_view(api, key='rental-map', height=330, listing_ids=None, compact=False, compared_ids=()):
    """compared_ids: the listings being compared, in the table's order. They show as numbered teal
    markers, even when not among listing_ids, and the map frames them with the faculty."""
    # The compact map fills its panel; a purple marker's position is approximate.
    if not compact:
        st.caption(t('Map positions come from V2 data. Inferred locations are approximate. The NUS anchor and commute estimates remain illustrative.', '地图位置来自 V2 数据，推断的位置是近似值。'))
    selected = st.session_state.selected_listing
    if not compact and st.button(t('Reset map view', '重置地图'), key=f'reset-{key}'):
        st.session_state.selected_listing = None
        st.rerun()
    map_object, positions = _listing_map(api, listing_ids, compared_ids, (), selected, compared_ids)
    try:
        result = st_folium(map_object, key=key, height=height, use_container_width=True, returned_objects=['last_object_clicked', 'last_object_clicked_tooltip'])
        candidate, signature = _clicked(result, positions)
        if candidate and signature != st.session_state.get(f'last-click-{key}'):
            st.session_state[f'last-click-{key}'] = signature
            st.session_state.selected_listing = candidate
            st.rerun()
    except Exception:
        st.warning(t('Map unavailable. Use the listing selector below; details and recommendations remain available.', '地图暂时不可用，可以用下面的列表选择房源。'))
    if compact:
        return
    st.caption(t('Home icon = V2 listing · Purple = inferred position · Graduation cap = your faculty or the NUS anchor. Map tiles © OpenStreetMap contributors; external tiles require internet.',
                 '房子图标 = 房源 · 紫色 = 推断的位置 · 学士帽 = 你的学院或 NUS 锚点。地图 © OpenStreetMap 贡献者，需要联网。'))
    if selected and selected not in positions:
        st.info(t('Selected listing has no usable data coordinates. Its source details remain available.', '选中的房源没有可用坐标，详情仍可查看。'))
    ids = [''] + list(positions)
    def select_listing():
        choice = st.session_state[f'select-{key}']
        if choice:
            st.session_state.selected_listing = choice
    st.session_state[f'select-{key}'] = selected if selected in ids else ''
    st.selectbox(t('Map listing selector', '地图房源列表'), ids, format_func=lambda value: t('Choose a data-positioned listing', '选择一套有坐标的房源') if not value else f'{api.details(value).facts["displayTitle"]} · {value}', key=f'select-{key}', on_change=select_listing)


def big_map(api, recommended_ids, favorite_ids, compared_ids, highlight, key='big-map'):
    """The enlarged map: the recommended, favorite and compared listings with the faculty, all in
    view, 600px high, and a legend. A click picks a listing without leaving the page: returns the
    listing picked by the latest click (None without one)."""
    shown = list(dict.fromkeys([*compared_ids, *favorite_ids, *recommended_ids]))
    map_object, positions = _listing_map(api, shown, compared_ids, favorite_ids, highlight, shown)
    picked = None
    try:
        result = st_folium(map_object, key=key, height=600, use_container_width=True, returned_objects=['last_object_clicked', 'last_object_clicked_tooltip'])
        picked = _clicked(result, positions)[0]
    except Exception:
        st.warning(t('Map unavailable.', '地图暂时不可用。'))
    st.caption(t('Numbered circle = being compared · Red heart = favorite · House = recommended (purple: inferred position) · Graduation cap = your faculty · Orange = selected',
                 '数字圆圈 = 比较中 · 红心 = 收藏 · 房子 = 推荐（紫色：推断的位置）· 学士帽 = 你的学院 · 橙色 = 当前选中'))
    if missing := len([listing_id for listing_id in shown if listing_id not in positions]):
        st.caption(t(f"{missing} listing{'s' if missing > 1 else ''} without coordinates {'are' if missing > 1 else 'is'} not on the map.", f'有 {missing} 套没有坐标，没在地图上显示。'))
    return picked
