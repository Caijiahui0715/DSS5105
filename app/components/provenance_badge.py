import streamlit as st
from domain.provenance import LABELS, display

def fact(label, value, provenance='source'):
    st.markdown(f'**{label}**')
    st.write(display(value))
    st.caption(LABELS['unavailable' if value in (None, 'unknown', '') else provenance])

def explanation():
    st.caption('Source data = supplied facts · Derived value = calculation · Demo estimate = illustrative · Not available = not supplied')
