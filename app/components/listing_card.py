import streamlit as st
from data.demo_enrichment import DEMO
from data.image_loader import source_image
from domain.provenance import display
from state.session_store import toggle_favorite, toggle_compare
from components.source_notes import source_notes

STATUS_LABELS = {'pass':'Pass', 'needs_confirmation':'Needs confirmation', 'fail':'Fail'}

def image(listing):
    content = source_image(listing.images[0]) if listing.images else None
    if content:
        st.image(content, width='stretch', caption='Historical V1 source listing image')
    else:
        st.info('Listing image unavailable. View the original listing for photos.', icon=':material/image:')

def actions(listing, key):
    a,b,c = st.columns(3)
    if a.button('Details', key=f'details-{key}', width='stretch'):
        st.session_state.selected_listing = listing.id
        st.rerun()
    saved = listing.id in st.session_state.favorites
    if b.button('Unsave' if saved else 'Save', key=f'save-{key}', width='stretch'):
        toggle_favorite(listing.id)
        st.rerun()
    if c.button('Remove compare' if listing.id in st.session_state.compare else 'Compare', key=f'compare-{key}', width='stretch'):
        toggle_compare(listing.id)
        st.rerun()

def card(listing, rec, key):
    f = listing.facts
    with st.container(border=True):
        st.caption(f'#{rec.rank} · {STATUS_LABELS[rec.evaluation.status]} · Demo recommendation')
        st.subheader(f['displayTitle'])
        if listing.provenance['displayTitle'] == 'derived':
            st.caption('English source-title excerpt · Derived display')
        st.markdown(f"### SGD {f['effectiveRentMonthlySgd']:,.0f} / month")
        source_notes(listing)
        image(listing)
        st.write(f"{display(f['propertyType'])} · {display(f['roomType'])} · {f['districtCode']}")
        st.caption(f['address'])
        st.write(f"**{rec.score} / 100** — {rec.match_level}")
        st.caption('Demo match score · unknown factors reduce evidence coverage')
        st.write(f"MRT: {display(f['mrtStation'])}")
        commute = DEMO.get(listing.id, {}).get('commute')
        st.caption(f'Estimated demo commute: {commute} min' if commute is not None else 'NUS commute: Not available')
        for reason in rec.reasons[:2]:
            st.write(f'✓ {reason}')
        if rec.tradeoffs:
            st.caption(rec.tradeoffs[0])
        if listing.metadata['reviewFlags']:
            st.warning('Data needs review', icon=':material/info:')
        actions(listing, key)
        if st.button('View on map', key=f'view-map-{key}'):
            st.session_state.selected_listing = listing.id
            st.session_state.page = 'Home'
            st.rerun()
        st.link_button('View original listing', f['listingUrl'])
