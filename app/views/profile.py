from dataclasses import replace
import streamlit as st
from state.session_store import current

def render(api):
    st.title('Profile')
    st.caption('Changes are saved only in the active Streamlit session. Passwords are never stored.')
    req,pref = st.session_state.requirements,st.session_state.preferences
    revision = st.session_state.get('profile-revision', 0)
    with st.form(f'profile-form-{revision}'):
        st.subheader('Personal information')
        name = st.text_input('Name',st.session_state.profile['name'])
        email = st.text_input('Email',st.session_state.profile['email'])
        st.subheader('Hard rental requirements')
        a,b,c = st.columns(3)
        budget = a.number_input('Maximum advertised monthly budget (SGD)',min_value=1,value=int(req.max_budget or 2500))
        scopes = ['No requirement','room','entire_unit']
        scope = b.selectbox('Rental scope',scopes,index=scopes.index(req.rental_scope or 'No requirement'),format_func=lambda v:{'room':'Shared accommodation / room','entire_unit':'Entire unit'}.get(v,v))
        bed_required = c.checkbox('Require a minimum bedroom count',value=req.min_bedrooms is not None)
        bedrooms = c.number_input('Minimum bedrooms',min_value=0,max_value=20,value=req.min_bedrooms or 0)
        st.subheader('Soft preferences')
        district_codes = [d['district_code'] for d in api.sources['districts']]
        district_names = {d['district_code']:d['district'] for d in api.sources['districts']}
        districts = st.multiselect('Preferred districts',district_codes,default=pref.districts,format_func=lambda code:f'{code} · {district_names[code]}')
        a,b = st.columns(2)
        mrt = a.number_input('Preferred maximum MRT distance (m)',min_value=100,value=pref.mrt_distance)
        commute = b.number_input('Preferred maximum NUS commute (min; demo estimate)',min_value=1,value=pref.commute_minutes)
        properties = ['No preference']+sorted({listing.facts['propertyType'] for listing in api.all_listings()})
        property_type = st.selectbox('Preferred property type',properties,index=properties.index(pref.property_type))
        options = {'furnishing':['No preference','fully_furnished','partially_furnished','unfurnished'], 'private_bathroom':['No preference','yes','no'],'cooking':['No preference','allowed','light_only','not_allowed'],'air_conditioning':['No preference','yes','no'],'pets':['No preference','allowed','not_allowed']}
        labels = {'furnishing':'Furnishing','private_bathroom':'Private bathroom','cooking':'Cooking','air_conditioning':'Air conditioning','pets':'Pets'}
        values = {key:st.selectbox(labels[key],choices,index=choices.index(getattr(pref,key)),format_func=lambda v:v.replace('_',' ').capitalize()) for key,choices in options.items()}
        save,cancel = st.columns(2)
        submitted = save.form_submit_button('Save profile',type='primary')
        canceled = cancel.form_submit_button('Cancel changes')
    if submitted:
        if not name.strip() or '@' not in email:
            st.error('Provide your name and a valid email.')
        else:
            st.session_state.profile = {'name':name.strip(),'email':email.strip()}
            st.session_state.requirements = replace(req,max_budget=float(budget),rental_scope=None if scope=='No requirement' else scope,min_bedrooms=int(bedrooms) if bed_required else None)
            st.session_state.preferences = replace(pref,districts=districts,mrt_distance=int(mrt) if mrt is not None else None,commute_minutes=int(commute) if commute is not None else None,property_type=property_type,**values)
            conv = current()
            conv['requirements'],conv['preferences'] = st.session_state.requirements,st.session_state.preferences
            conv['recommendations'] = api.recommendations(conv['requirements'],conv['preferences'])
            st.session_state.notice = 'Profile saved for this session. Recommendations updated.'
            st.session_state['profile-revision'] = revision + 1
            st.rerun()
    if canceled:
        st.session_state['profile-revision'] = revision + 1
        st.rerun()
