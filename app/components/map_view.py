import html
import folium
import streamlit as st
from streamlit_folium import st_folium
from data.demo_enrichment import NUS_POSITION
from content.i18n import t
from domain.location import coordinates, location_note
from state.session_store import live, current_faculty


def anchor():
    """The map's reference point: the user's faculty, or the illustrative NUS point."""
    faculty = current_faculty() if live() else None
    if faculty is None:
        return NUS_POSITION, t('NUS (choose your faculty in Profile)', 'NUS（可在个人资料里选择学院）') if live() else t('NUS demo campus anchor', 'NUS 演示校园锚点')
    return (faculty['latitude'], faculty['longitude']), t(faculty['name'], faculty['zh'])

def map_view(api, key='rental-map', height=330, listing_ids=None, compact=False):
    # The compact map fills its panel; each marker's tooltip says when a position is approximate.
    if not compact:
        st.caption(t('Map positions come from V2 data. Inferred locations are approximate. The NUS anchor and commute estimates remain illustrative.', '地图位置来自 V2 数据，推断的位置是近似值。'))
    home, home_name = anchor()
    selected = st.session_state.selected_listing
    allowed = None if listing_ids is None else set(listing_ids)
    positioned = [listing for listing in api.all_listings() if coordinates(listing) is not None and (allowed is None or listing.id in allowed)]
    positions = {listing.id: coordinates(listing) for listing in positioned}
    if not compact and st.button(t('Reset map view', '重置地图'), key=f'reset-{key}'):
        st.session_state.selected_listing = None
        st.rerun()
    center = positions.get(selected, home)
    map_object = folium.Map(location=center, zoom_start=14 if selected in positions else 12, tiles='OpenStreetMap', control_scale=True)
    if listing_ids is None or positioned:
        folium.Marker(home, tooltip=html.escape(home_name), icon=folium.Icon(color='darkblue', icon='graduation-cap', prefix='fa')).add_to(map_object)
    for listing in positioned:
        f = listing.facts
        inferred = listing.provenance['coordinates'] == 'derived'
        folium.Marker(positions[listing.id], tooltip=f'{listing.id} | {html.escape(f["displayTitle"])} | SGD {f["effectiveRentMonthlySgd"]:,.0f} | {html.escape(location_note(listing))}', popup=f'{listing.id} | {html.escape(location_note(listing))}', icon=folium.Icon(color='orange' if selected == listing.id else 'purple' if inferred else 'blue', icon='home', prefix='fa')).add_to(map_object)
    try:
        result = st_folium(map_object, key=key, height=height, use_container_width=True, returned_objects=['last_object_clicked', 'last_object_clicked_tooltip'])
        tooltip = result.get('last_object_clicked_tooltip') if result else None
        clicked = result.get('last_object_clicked') if result else None
        candidate = str(tooltip).split(' | ')[0] if tooltip else None
        if candidate not in positions and isinstance(clicked, dict):
            matches = [listing_id for listing_id, position in positions.items() if abs(position[0]-clicked.get('lat',0)) < .00001 and abs(position[1]-clicked.get('lng',0)) < .00001]
            # Shared addresses can have identical coordinates; do not guess an ID.
            candidate = matches[0] if len(matches) == 1 else None
        signature = str((candidate, clicked))
        if candidate in {listing.id for listing in positioned} and signature != st.session_state.get(f'last-click-{key}'):
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
    ids = [''] + [listing.id for listing in positioned]
    def select_listing():
        choice = st.session_state[f'select-{key}']
        if choice:
            st.session_state.selected_listing = choice
    st.session_state[f'select-{key}'] = selected if selected in ids else ''
    st.selectbox(t('Map listing selector', '地图房源列表'), ids, format_func=lambda value: t('Choose a data-positioned listing', '选择一套有坐标的房源') if not value else f'{api.details(value).facts["displayTitle"]} · {value}', key=f'select-{key}', on_change=select_listing)
