import pandas as pd
import streamlit as st
from data.evaluation_fixtures import SCENARIOS, DIMENSIONS, BASELINES

def render(api):
    st.title('Evaluation')
    st.info('Pending evaluation. Recommendation quality and production system performance have not yet been measured.')
    st.subheader('Scenario plan')
    st.dataframe(pd.DataFrame([{'Scenario':item['query'],'Expected constraints':item['expected'],'Result status':'Pending evaluation'} for item in SCENARIOS]),hide_index=True,width='stretch',column_config={'Scenario':st.column_config.TextColumn(width=270),'Expected constraints':st.column_config.TextColumn(width=470),'Result status':st.column_config.TextColumn(width=170)})
    a,b = st.columns(2)
    with a:
        st.subheader('Evaluation dimensions')
        for dimension in DIMENSIONS:
            st.write(f'• {dimension}: Not yet measured')
    with b:
        st.subheader('Proposed baselines')
        for baseline in BASELINES:
            st.write(f'• {baseline}: Pending evaluation')
    with st.expander('Source-data validation — separate from recommendation evaluation'):
        st.write('Current V2 snapshot:')
        st.json(api.sources['snapshot'])
        st.write('Historical V1 validation report:')
        st.json(api.sources['validation'])
        st.caption('The supplied report applies to historical V1, not the refreshed V2 dataset. It does not measure recommendation quality or production performance.')
