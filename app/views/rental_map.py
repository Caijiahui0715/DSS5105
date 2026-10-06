import streamlit as st
from components.map_view import map_view
from components.listing_details import details
from views.recommendations import active_recommendations

def render(api):
    st.title('Rental Map')
    st.write('Explore V2 data locations alongside listing facts. Inferred positions are approximate.')
    left,right = st.columns([2,1])
    with left:
        map_view(api,key='full-map',height=520)
        listings = api.all_listings()
        ids = [''] + [listing.id for listing in listings]
        selected = st.session_state.selected_listing
        def select_listing():
            if st.session_state['all-listing-selector']:
                st.session_state.selected_listing = st.session_state['all-listing-selector']
        st.session_state['all-listing-selector'] = selected if selected in ids else ''
        st.selectbox(f'All {len(listings)} active snapshot listings',ids,format_func=lambda value:'Choose a source listing' if not value else f'{api.details(value).facts["displayTitle"]} · {value}',key='all-listing-selector',on_change=select_listing)
    with right:
        selected = st.session_state.selected_listing
        rec = next((r for r in active_recommendations(api) if r.listing_id==selected),None)
        details(api.details(selected) if selected else None,rec,'map-selected')
