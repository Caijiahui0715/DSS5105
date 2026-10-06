import pandas as pd
import streamlit as st
from domain.provenance import display
from data.demo_enrichment import DEMO

def comparison(api, recommendations):
    ids = st.session_state.compare
    if not ids:
        st.info('Use Compare on a listing to compare up to three options.')
        return
    st.subheader(f'Compare {len(ids)} listings')
    index = {rec.listing_id:rec for rec in recommendations}
    rows = {}
    for listing_id in ids[:3]:
        listing = api.details(listing_id)
        if listing is None:
            st.warning(f'Listing {listing_id} is outside the current active snapshot and cannot be compared.')
            continue
        f = listing.facts
        rec = index.get(listing_id)
        values = {label:display(f[field]) for label,field in [('Latest recorded rent (SGD)','effectiveRentMonthlySgd'),('Original advertised rent (SGD)','rentMonthlySgd'),('Snapshot status','scrapeStatus'),('Last checked','enrichedAt'),('District','districtName'),('MRT','mrtStation'),('Property type','propertyType'),('Rental scope','rentalScope'),('Room type','roomType'),('Bedrooms','bedrooms'),('Bathrooms','bathrooms'),('Area (sqm)','areaSqm'),('Area scope','areaScope'),('Furnishing','furnishing')]}
        values.update({'Constraint status': rec.evaluation.status if rec else 'Not in current eligible results', 'Demo match score': f'{rec.score}/100' if rec else 'Not available', 'Estimated demo commute':display(DEMO.get(listing_id,{}).get('commute')), 'Historical V1 availability':display(listing.metadata['availabilityStatus']), 'Demo reasons':' | '.join(rec.reasons) if rec else 'Not available', 'Trade-offs':' | '.join(rec.tradeoffs) if rec else 'Re-evaluate current constraints', 'Unknown information':', '.join(rec.unknown_factors) if rec else 'Not available'})
        rows[f'{f["displayTitle"]} ({listing_id})'] = values
    st.dataframe(pd.DataFrame(rows), width='stretch')
    st.caption('Source facts except clearly labelled demo scores, commute and explanations. Availability is not verified in real time.')
    if st.button('Clear comparison'):
        st.session_state.compare = []
        st.rerun()
