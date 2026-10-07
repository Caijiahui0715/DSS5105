import streamlit as st


def source_notes(listing):
    f = listing.facts
    label = 'Refreshed advertised rent' if f.get('rentSource') == 'refreshed_advertised' else 'Original advertised rent fallback; refreshed price unavailable'
    st.caption(f'{label} · additional costs not confirmed')
    st.caption(f"Active at snapshot · checked {f.get('enrichedAt') or 'Not provided'} (timezone unconfirmed)")
    st.caption('Link status at that snapshot does not confirm availability now.')
