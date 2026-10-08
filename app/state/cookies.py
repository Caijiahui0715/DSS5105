"""Remember me on this device: the backend's sign-in token in a browser cookie for seven days.

Streamlit reads the cookies sent with the page (st.context.cookies). Writing one takes a line of
JavaScript in an invisible component, which cannot render inside a button callback: callbacks only
ask for it (st.session_state['cookie-action'] = token or 'delete') and apply() writes it on the
next run. The component sends nothing back, so writing the cookie never restarts the page while
the agent is replying.
"""
import json
import streamlit as st
import streamlit.components.v1 as components

COOKIE = 'nus_rental_token'
SECONDS = 7 * 24 * 3600  # the backend's token lifetime


def saved_token():
    """The token in the cookie this page was opened with; offered once per browser session, so a
    sign-out in this tab is not undone by the cookie the page was opened with."""
    if st.session_state.get('cookie-checked'):
        return None
    st.session_state['cookie-checked'] = True
    return st.context.cookies.get(COOKIE) or None


def apply():
    action = st.session_state.pop('cookie-action', None)
    if action is None:
        return
    # Deleting is writing it again, already expired.
    value, seconds = ('', 0) if action == 'delete' else (action, SECONDS)
    cookie = f'{COOKIE}={value}; path=/; max-age={seconds}; SameSite=Lax'
    with st.container(key='cookie-writer'):
        components.html(f'<script>window.parent.document.cookie = {json.dumps(cookie)};</script>', height=0)
