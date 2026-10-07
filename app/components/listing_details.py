import streamlit as st
import json
import re
from components.listing_card import image, actions, STATUS_LABELS
from components.provenance_badge import fact, explanation
from data.demo_enrichment import DEMO
from domain.location import coordinates, location_note
from components.source_notes import source_notes

def details(listing, recommendation=None, key='detail'):
    if listing is None:
        st.info('Select a listing card, map marker, or the listing selector to explore details.')
        return
    f = listing.facts
    st.subheader(f['displayTitle'])
    if listing.provenance['displayTitle'] == 'derived':
        st.caption('Derived display: English excerpt from the original bilingual title. Original source record is unchanged.')
    image(listing)
    fact('Latest recorded monthly rent (SGD)', f['effectiveRentMonthlySgd'])
    fact('Original advertised monthly rent (SGD)', f['rentMonthlySgd'])
    source_notes(listing)
    fact('Price type', f['rentPriceType'])
    st.caption('This is not a confirmed total monthly housing cost.')
    if recommendation:
        st.write(f'**Demo match score: {recommendation.score} / 100** — {recommendation.match_level}')
        st.write(f'Constraint status: {STATUS_LABELS[recommendation.evaluation.status]}')
        with st.expander('Why it matches, trade-offs and unknowns'):
            for reason in recommendation.reasons:
                st.write(f'✓ {reason}')
            for tradeoff in recommendation.tradeoffs:
                st.write(f'• {tradeoff}')
            st.write('Unknown factors:', ', '.join(recommendation.unknown_factors))
            st.write('Demo score components (0–1; missing = no points):')
            st.json(recommendation.breakdown)
            st.json(recommendation.evaluation.checks)
    with st.expander('Property and location', expanded=True):
        for label, field in [('Rental scope','rentalScope'),('Property type','propertyType'),('Room type','roomType'),('Bedrooms','bedrooms'),('Bathrooms','bathrooms'),('Area (sqm)','areaSqm'),('Area scope','areaScope'),('District','districtName'),('Address','address'),('Advertised MRT','mrtStation'),('MRT distance (m)','mrtDistanceM'),('Reported MRT minutes','mrtMinutesReported'),('MRT operation status','mrtOperationStatus')]:
            fact(label, f[field], listing.provenance[field])
        st.caption('Bathroom count does not imply private use. Advertised MRT minutes are not NUS commute time; station operation may be unknown.')
        fact('Estimated demo NUS commute (min)', DEMO.get(listing.id, {}).get('commute'), 'mock')
        fact('Data map coordinates', coordinates(listing), listing.provenance['coordinates'])
        st.caption(location_note(listing))
        fact('Postcode', f.get('postcode'))
        fact('Street', f.get('streetName'))
    with st.expander('Furnishing and lifestyle'):
        for label, field in [('Furnishing','furnishing'),('Private bathroom','privateBathroom'),('Cooking','cookingPolicy'),('Air conditioning','airConditioning'),('Landlord lives in','landlordLivesIn'),('Pets policy','petsPolicy'),('Reported tenant count','tenantCountReported'),('Platform gender label','tenantGenderLabel'),('Explicit gender restriction','genderRestriction'),('Gender preference','genderPreference')]:
            fact(label, f[field], listing.provenance[field])
        st.caption('Tenant count is not confirmed occupancy capacity. Platform labels are not verified roommate information; preferences are not exclusion rules.')
    with st.expander('Availability, review and provenance'):
        fact('V2 snapshot link status', f.get('scrapeStatus'))
        fact('V2 last checked', f.get('enrichedAt'))
        fact('Historical V1 availability status', listing.metadata['availabilityStatus'])
        fact('Historical V1 availability text', listing.evidence['availabilityText'])
        st.warning('Listing availability has not been verified in real time.')
        fact('Listed date', f['listedDate'])
        fact('Collected at (timezone unconfirmed)', f['collectedAt'])
        if listing.metadata['reviewFlags']:
            st.write('Data needs review:', ', '.join(listing.metadata['reviewFlags']))
        else:
            st.caption('No recorded flags. This does not mean every fact has been verified.')
        st.caption('Review flags identify checks to make; they do not prove an error.')
        explanation()
        st.json(listing.provenance)
        st.write('Original V2 categorical labels (before UI normalization):')
        st.json({field: listing.source_fields.get(field) for field in ('cooking_policy', 'pets_policy')})
        st.write('Source card text:')
        text = listing.evidence.get('cardText') or 'Not provided'
        if re.search('[\u3400-\u9fff]',text):
            st.caption('The original advertisement includes non-English text. Use the original listing link to inspect it; the source record has been preserved without translation.')
        else:
            st.text(text)
        with st.expander('Source extraction evidence'):
            evidence = {k:v for k,v in listing.evidence.items() if k in ('fieldEvidence','ruleEvidence')}
            if re.search('[\u3400-\u9fff]',json.dumps(evidence,ensure_ascii=False)):
                st.caption('Non-English source evidence remains in the supplied evidence file. It is not translated or reproduced here.')
            else:
                st.json(evidence)
    actions(listing, key)
    st.link_button('View original listing', f['listingUrl'], width='stretch')
    st.caption('Historical source links may be unavailable or changed.')


def compact_details(listing, recommendation):
    """Small source-grounded card inside the fixed Home detail panel."""
    from domain.provenance import display
    f = listing.facts
    st.subheader(f['displayTitle'])
    if listing.provenance['displayTitle'] == 'derived':
        st.caption('English source-title excerpt · Derived display')
    st.markdown(f"**SGD {f['effectiveRentMonthlySgd']:,.0f} / month** · {display(f['rentPriceType'])}")
    source_notes(listing)
    st.write(f"{display(f['propertyType'])} · {display(f['rentalScope'])}")
    st.caption(f"{f['districtCode']} · {f['address']}")
    st.write(f"**{recommendation.score} / 100** · Demo match score")
    st.caption(STATUS_LABELS[recommendation.evaluation.status])
    st.caption(f"MRT: {display(f['mrtStation'])}")
    commute = DEMO.get(listing.id, {}).get('commute')
    st.caption(f'Estimated demo commute: {commute} min' if commute is not None else 'NUS commute: Not available')
    if listing.metadata['reviewFlags']:
        st.caption('Data needs review')
    for reason in recommendation.reasons[:2]:
        st.caption(reason)
    actions(listing, 'home-selected')
    with st.expander('Listing facts and provenance'):
        fact('Original advertised monthly rent (SGD)', f['rentMonthlySgd'])
        fact('Refreshed advertised monthly rent (SGD)', f.get('rentMonthlySgdNow'))
        for label, field in [('Room type','roomType'), ('Bedrooms','bedrooms'), ('Bathrooms','bathrooms'), ('Area (sqm)','areaSqm'), ('Area scope','areaScope'), ('MRT distance (m)','mrtDistanceM'), ('Reported MRT minutes','mrtMinutesReported'), ('Furnishing','furnishing'), ('Private bathroom','privateBathroom'), ('Cooking','cookingPolicy'), ('Air conditioning','airConditioning'), ('Pets','petsPolicy')]:
            fact(label, f[field], listing.provenance[field])
        fact('V2 snapshot link status', f.get('scrapeStatus'))
        fact('Data map coordinates', coordinates(listing), listing.provenance['coordinates'])
        st.caption(location_note(listing))
        fact('Historical V1 availability', listing.metadata['availabilityStatus'])
        st.caption('Listing availability has not been verified in real time.')
        st.caption('Bathrooms do not imply private use; reported MRT minutes are not NUS commute.')
        st.write('Trade-offs:', ' · '.join(recommendation.tradeoffs))
        explanation()
    st.link_button('View original listing', f['listingUrl'])
