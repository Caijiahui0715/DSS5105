import streamlit as st
from components.listing_card import card
from components.listing_details import details
from components.comparison import comparison
from views.recommendations import active_recommendations
from domain.recommendation import evaluate
from data.demo_enrichment import demo_score
from domain.models import Recommendation
from state.session_store import current

def render(api):
    st.title('Favorites')
    st.caption('Saved listings persist only during the active Streamlit session.')
    if not st.session_state.favorites:
        st.info('No saved listings yet. Save an option from Chat, Recommendations or the map.')
        return
    recs = active_recommendations(api)
    index = {rec.listing_id:rec for rec in recs}
    conv = current()
    for listing_id in st.session_state.favorites:
        if api.details(listing_id) is None:
            continue
        if listing_id not in index:
            listing = api.details(listing_id)
            score,breakdown,reasons,tradeoffs,unknown = demo_score(listing,conv['requirements'],conv['preferences'])
            index[listing_id] = Recommendation(listing_id,0,score,'Outside current eligible recommendations',evaluate(listing,conv['requirements']),reasons,tradeoffs,unknown,breakdown)
    comparison(api,list(index.values()))
    for listing_id,saved in list(st.session_state.favorites.items()):
        st.caption(f'Saved at {saved} (session time)')
        if api.details(listing_id) is None:
            st.warning(f'Listing {listing_id} is outside the current active snapshot. It is not offered as a recommendation.')
            if st.button('Remove unavailable favorite', key=f'remove-unavailable-{listing_id}'):
                del st.session_state.favorites[listing_id]
                st.rerun()
            continue
        card(api.details(listing_id),index[listing_id],f'fav-{listing_id}')
    selected = st.session_state.selected_listing
    if selected:
        details(api.details(selected),index.get(selected),'fav-selected')
