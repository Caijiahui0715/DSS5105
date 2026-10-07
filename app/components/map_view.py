import html
import folium
import streamlit as st
from streamlit_folium import st_folium
from data.demo_enrichment import NUS_POSITION, MAP_NOTICE
from domain.location import coordinates, location_note

def map_view(api, key='rental-map', height=330, listing_ids=None, compact=False):
    st.caption('V2 data locations · inferred positions approximate' if compact else MAP_NOTICE)
    selected = st.session_state.selected_listing
    allowed = None if listing_ids is None else set(listing_ids)
    positioned = [listing for listing in api.all_listings() if coordinates(listing) is not None and (allowed is None or listing.id in allowed)]
    positions = {listing.id: coordinates(listing) for listing in positioned}
    if not compact and st.button('Reset map view', key=f'reset-{key}'):
        st.session_state.selected_listing = None
        st.rerun()
    center = positions.get(selected, NUS_POSITION)
    map_object = folium.Map(location=center, zoom_start=14 if selected in positions else 12, tiles='OpenStreetMap', control_scale=True)
    if listing_ids is None or positioned:
        folium.Marker(NUS_POSITION, tooltip='NUS demo campus anchor', icon=folium.Icon(color='darkblue', icon='graduation-cap', prefix='fa')).add_to(map_object)
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
        st.warning('Map unavailable. Use the listing selector below; details and recommendations remain available.')
    if compact:
        return
    st.caption('Home icon = V2 listing · Purple = inferred position · Graduation cap = illustrative NUS anchor. Map tiles © OpenStreetMap contributors; external tiles require internet.')
    if selected and selected not in positions:
        st.info('Selected listing has no usable data coordinates. Its source details remain available.')
    ids = [''] + [listing.id for listing in positioned]
    def select_listing():
        choice = st.session_state[f'select-{key}']
        if choice:
            st.session_state.selected_listing = choice
    st.session_state[f'select-{key}'] = selected if selected in ids else ''
    st.selectbox('Map listing selector', ids, format_func=lambda value: 'Choose a data-positioned listing' if not value else f'{api.details(value).facts["displayTitle"]} · {value}', key=f'select-{key}', on_change=select_listing)
