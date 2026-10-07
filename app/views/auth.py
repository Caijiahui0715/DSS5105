import streamlit as st
from content.en import PRODUCT, TAGLINE
from domain.models import RentalRequirements, RentalPreferences
from state.session_store import current
from data.source_loader import load_sources

def submit(mode, skip_preferences=False):
    # Callback executes before rerender: delete password widget state immediately.
    name = st.session_state.get(f'{mode}-name','').strip()
    email = st.session_state.get(f'{mode}-email','').strip()
    password = st.session_state.pop(f'{mode}-password', '')
    valid = bool(name and '@' in email and len(password) >= 6)
    del password
    error = None if valid else 'Enter your name, a valid email, and a password of at least six characters.'
    if mode == 'register':
        budget = st.session_state.get('register-budget')
        scope = st.session_state.get('register-scope')
        bedrooms = st.session_state.get('register-bedrooms')
        if budget is None or budget <= 0 or scope not in ('room', 'entire_unit') or bedrooms is None:
            valid = False
            error = 'Complete all hard requirements: monthly budget, rental scope, and minimum bedroom choice. These cannot be skipped.'
        if valid:
            st.session_state.requirements = RentalRequirements(float(budget), scope, None if bedrooms == 'No minimum' else int(bedrooms))
            pref = RentalPreferences(districts=[], mrt_distance=None, commute_minutes=None)
            if not skip_preferences:
                pref.districts = list(st.session_state.get('register-districts', []))
                pref.mrt_distance = st.session_state.get('register-mrt')
                pref.commute_minutes = st.session_state.get('register-commute')
                for field in ('furnishing', 'private_bathroom', 'cooking', 'air_conditioning', 'pets', 'property_type'):
                    setattr(pref, field, st.session_state.get(f'register-{field}', 'No preference'))
            st.session_state.preferences = pref
            conv = current()
            conv['requirements'], conv['preferences'] = st.session_state.requirements, pref
            conv['recommendations'] = None
    st.session_state['auth-error'] = error
    if valid:
        st.session_state.profile = {'name':name, 'email':email}
        st.session_state.authenticated = True
        st.session_state.page = 'Home'

def render():
    _, main, _ = st.columns([1,2,1])
    with main:
        st.caption('DSS5105 Student Project')
        st.title(PRODUCT)
        st.subheader(TAGLINE)
        st.write('Make a more informed rental decision with real static listings, transparent trade-offs and a conversational demo.')
        st.info('Demo authentication only. No identity verification or database persistence. Passwords are discarded on submission.')
        login, register = st.tabs(['Login', 'Register'])
        for tab, mode in [(login,'login'),(register,'register')]:
            with tab:
                with st.form(f'{mode}-form', clear_on_submit=False):
                    st.text_input('Name', key=f'{mode}-name')
                    st.text_input('Email', key=f'{mode}-email')
                    st.text_input('Password', type='password', key=f'{mode}-password')
                    if mode == 'register':
                        st.subheader('Hard rental requirements · Required')
                        st.caption('Complete every field below. Hard requirements cannot be skipped.')
                        st.number_input('Maximum advertised monthly budget (SGD) *', min_value=1, value=None, step=100, key='register-budget', placeholder='Enter your monthly budget')
                        st.selectbox('Rental scope *', ['room', 'entire_unit'], index=None, key='register-scope', placeholder='Choose a rental scope', format_func=lambda v: {'room':'Shared accommodation / room', 'entire_unit':'Entire unit'}[v])
                        st.selectbox('Minimum bedrooms *', ['No minimum', *range(1, 21)], index=None, key='register-bedrooms', placeholder='Choose a minimum or explicitly select No minimum')
                        with st.expander('Soft preferences · Optional'):
                            st.caption('Leave these blank or skip them. You can update them later in Profile.')
                            sources = load_sources()
                            districts = {d['district_code']:d['district'] for d in sources['districts']}
                            st.multiselect('Preferred districts', list(districts), key='register-districts', format_func=lambda v:f'{v} · {districts[v]}')
                            st.number_input('Preferred maximum MRT distance (m)', min_value=100, value=None, key='register-mrt')
                            st.number_input('Preferred maximum NUS commute (min; demo estimate)', min_value=1, value=None, key='register-commute')
                            properties = sorted({listing.facts['propertyType'] for listing in sources['listings']})
                            options = {'property_type': ['No preference', *properties], 'furnishing':['No preference','fully_furnished','partially_furnished','unfurnished'], 'private_bathroom':['No preference','yes','no'], 'cooking':['No preference','allowed','light_only','not_allowed'], 'air_conditioning':['No preference','yes','no'], 'pets':['No preference','allowed','not_allowed']}
                            labels = {'property_type':'Property type', 'furnishing':'Furnishing', 'private_bathroom':'Private bathroom', 'cooking':'Cooking', 'air_conditioning':'Air conditioning', 'pets':'Pets'}
                            for field, choices in options.items():
                                st.selectbox(labels[field], choices, key=f'register-{field}', format_func=lambda v:v.replace('_',' ').capitalize())
                    st.form_submit_button('Sign in' if mode == 'login' else 'Create demo profile', on_click=submit, args=(mode,), type='primary')
                    if mode == 'register':
                        st.form_submit_button('Skip soft preferences and create profile', on_click=submit, args=(mode, True))
        if st.session_state.get('auth-error'):
            st.error(st.session_state['auth-error'])
        if st.button('Continue with demo account', width='stretch'):
            st.session_state.authenticated = True
            st.rerun()
