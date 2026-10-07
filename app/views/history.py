import streamlit as st
from state.session_store import new_conversation, navigate

def render():
    st.title('Conversation History')
    st.caption('Current-session history only. Refreshing or disconnecting may reset this history.')
    if st.button('Start a new conversation'):
        new_conversation()
        navigate('Home')
    for key,conv in reversed(list(st.session_state.conversations.items())):
        with st.container(border=True):
            st.subheader(conv['title'])
            st.caption(f'{len(conv["messages"])} messages · Updated {conv["updated"]}')
            if key == st.session_state.active_conversation:
                st.caption('Active conversation')
            if st.button('Reopen conversation',key=f'reopen-{key}'):
                st.session_state.active_conversation = key
                navigate('Home')
