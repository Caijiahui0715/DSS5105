import streamlit as st
from components.listing_card import card
from components.listing_details import details
from components.comparison import comparison
from data.demo_enrichment import DEMO, DEFAULT_WEIGHTS
from state.session_store import current

def active_recommendations(api):
    conv = current()
    return api.recommendations(conv['requirements'], conv['preferences'])

def render(api):
    st.title('Recommendations')
    st.caption('Real source listings · Demo match scores · Failed hard constraints excluded')
    with st.expander('How demo ranking works'):
        st.json(DEFAULT_WEIGHTS)
        st.write('Weights sum to 100%. Unknown components receive no points. Property condition is unavailable and is not assessed. Pass candidates are ranked before Needs confirmation candidates. No trained model or measured recommendation accuracy is claimed.')
    recs = active_recommendations(api)
    a,b,c = st.columns(3)
    sort = a.selectbox('Sort by', ['Best demo match','Lowest recorded rent','Shortest demo commute'])
    status = b.selectbox('Constraint status', ['All eligible','Pass','Needs confirmation'])
    search = c.text_input('Find title, district or address')
    filtered = [r for r in recs if status == 'All eligible' or r.evaluation.status == ('pass' if status == 'Pass' else 'needs_confirmation')]
    if search:
        filtered = [r for r in filtered if search.lower() in ' '.join(str(api.details(r.listing_id).facts[k]) for k in ('title','address','districtCode','districtName')).lower()]
    if sort == 'Lowest recorded rent':
        filtered.sort(key=lambda r: api.details(r.listing_id).facts['effectiveRentMonthlySgd'])
    elif sort == 'Shortest demo commute':
        filtered.sort(key=lambda r: DEMO.get(r.listing_id,{}).get('commute',float('inf')))
    st.caption(f'{len(filtered)} matching options. Scores and commute are demonstration-only.')
    comparison(api,recs)
    if not filtered:
        st.info('No results. Review the selected filters or edit your requirements in Profile.')
        return
    page = st.number_input('Results page',min_value=1,max_value=max(1,(len(filtered)+5)//6),value=1,key=f'result-page-{len(filtered)}')
    for offset in range(0,6,2):
        cols = st.columns(2)
        for col,rec in zip(cols,filtered[(page-1)*6+offset:(page-1)*6+offset+2]):
            with col:
                card(api.details(rec.listing_id),rec,f'recs-{rec.listing_id}')
    selected = st.session_state.selected_listing
    if selected:
        st.divider()
        details(api.details(selected),next((r for r in recs if r.listing_id==selected),None),'recs-selected')
