from datetime import datetime
from uuid import uuid4
import streamlit as st
from domain.models import RentalRequirements, RentalPreferences

def initialize():
    defaults = {'authenticated':False, 'profile':{'name':'Demo explorer','email':'demo@example.com'}, 'requirements':RentalRequirements(), 'preferences':RentalPreferences(), 'favorites':{}, 'compare':[], 'conversations':{}, 'active_conversation':None, 'selected_listing':None, 'page':'Home', 'notice':None}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    if st.session_state.active_conversation is None:
        new_conversation()

def new_conversation():
    key = str(uuid4())
    st.session_state.conversations[key] = {'title':'New conversation', 'messages':[], 'recommendations':None, 'requirements':st.session_state.requirements, 'preferences':st.session_state.preferences, 'updated':datetime.now().isoformat(timespec='seconds')}
    st.session_state.active_conversation = key

def current():
    return st.session_state.conversations[st.session_state.active_conversation]


def refresh_snapshot(api):
    version = api.sources.get('source_version')
    if version == st.session_state.get('rental-source-version'):
        return
    ids = {listing.id for listing in api.all_listings()}
    for conv in st.session_state.conversations.values():
        if conv['recommendations'] is not None:
            conv['recommendations'] = api.recommendations(conv['requirements'], conv['preferences'])
    st.session_state.compare = [listing_id for listing_id in st.session_state.compare if listing_id in ids]
    if st.session_state.selected_listing not in ids:
        st.session_state.selected_listing = None
    st.session_state['rental-source-version'] = version

def navigate(page):
    st.session_state.page = page
    st.rerun()

def toggle_favorite(listing_id):
    if listing_id in st.session_state.favorites:
        del st.session_state.favorites[listing_id]
        st.session_state.notice = 'Favorite removed.'
    else:
        st.session_state.favorites[listing_id] = datetime.now().isoformat(timespec='seconds')
        st.session_state.notice = 'Saved for this session.'

def toggle_compare(listing_id):
    ids = st.session_state.compare
    if listing_id in ids:
        ids.remove(listing_id)
    elif len(ids) < 3:
        ids.append(listing_id)
    else:
        st.session_state.notice = 'Compare up to three listings. Remove one before adding another.'

def logout():
    for key in list(st.session_state):
        del st.session_state[key]
    st.rerun()
