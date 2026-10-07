import streamlit as st
from state.session_store import navigate, new_conversation, logout


def navigation(compact=False):
    """Three persistent native-widget destinations; CSS fixes the icon rail."""
    with st.container(key='global-rail'):
        for page, icon in [('Home', 'home'), ('Favorites', 'bookmark'), ('Profile', 'person')]:
            if st.button(page, icon=f':material/{icon}:', help=page, key=f'nav-{page}', width='stretch', type='primary' if st.session_state.page == page else 'secondary'):
                navigate(page)


def open_conversation(key):
    st.session_state.active_conversation = key
    recs = st.session_state.conversations[key]['recommendations'] or []
    st.session_state.selected_listing = recs[0].listing_id if recs else None
    st.rerun()


def conversation_sidebar():
    with st.container(key='chat-history'):
        if st.button('Hide conversation history', icon=':material/left_panel_close:', key='close-history'):
            st.session_state.history_open = False
            st.rerun()
        st.markdown('### Your conversations')
        if st.button('New conversation', icon=':material/edit_square:', key='new-chat', width='stretch'):
            new_conversation()
            st.session_state.selected_listing = None
            st.rerun()
        st.caption('Current session')
        for key, conv in reversed(list(st.session_state.conversations.items())):
            if st.button(conv['title'], key=f'recent-{key}', width='stretch', type='primary' if key == st.session_state.active_conversation else 'secondary'):
                open_conversation(key)
        st.divider()
        st.caption('History and saved listings last for this session only.')
        st.caption(st.session_state.profile['name'])
        if st.button('Log out', icon=':material/logout:'):
            logout()
