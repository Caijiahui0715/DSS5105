from datetime import datetime
import streamlit as st
from components.navigation import conversation_sidebar
from components.map_view import map_view
from components.listing_details import compact_details
from content.en import PROMPTS
from state.session_store import current
from domain.models import ApiError


def send(message, agent):
    conv = current()
    try:
        with st.spinner('Searching static listings…'):
            response = agent.respond(message, conv['requirements'], conv['preferences'], conv['messages'])
        conv['messages'].extend([{'role': 'user', 'text': message}, {'role': 'assistant', 'text': response.text, 'clarification': response.clarification}])
        if conv['title'] == 'New conversation':
            conv['title'] = message[:55]
        conv['requirements'], conv['preferences'] = response.requirements, response.preferences
        conv['recommendations'] = response.recommendations
        conv['updated'] = datetime.now().isoformat(timespec='seconds')
        st.session_state.selected_listing = response.recommendations[0].listing_id if response.recommendations else None
        st.rerun()
    except ApiError as exc:
        st.error(str(exc))


def render(api, agent):
    if st.session_state.get('history_open', True):
        conversation_sidebar()
    conv = current()
    recs = conv['recommendations'] or []
    eligible_ids = [rec.listing_id for rec in recs]
    if not recs:
        st.session_state.selected_listing = None
    elif st.session_state.selected_listing not in eligible_ids:
        st.session_state.selected_listing = recs[0].listing_id
    center, right = st.columns([2.2, 1.5], gap='medium')
    with center:
        with st.container(key='chat-header'):
            if st.button('Toggle conversation history', icon=':material/menu:', help='Show or hide conversation history', key='toggle-history'):
                st.session_state.history_open = not st.session_state.get('history_open', True)
                st.rerun()
        with st.container(height=580, border=False, key='chat-thread'):
            if not conv['messages']:
                st.markdown('## How can I help with your rental search?')
            for index, message in enumerate(conv['messages']):
                with st.container(key=f"chat-{message['role']}-{index}"):
                    with st.chat_message(message['role']):
                        st.write(message['text'])
                        if message.get('clarification'):
                            st.warning(message['clarification'])
        if message := st.chat_input('Message the rental Agent', key='rental-chat-input'):
            send(message, agent)
    with right:
        with st.container(height=340, border=True, key='map-panel'):
            map_view(api, key='home-map', height=250, listing_ids=eligible_ids, compact=True)
        with st.container(height=420, border=True, key='listing-panel'):
            if not recs:
                st.caption('Your recommended listings will appear here.')
                st.markdown('**Try a rental request**')
                for i, prompt in enumerate(PROMPTS):
                    if st.button(prompt, key=f'prompt-{i}', width='stretch'):
                        send(prompt, agent)
                if conv['recommendations'] == []:
                    st.caption('No recommended listings for this request. Try clarifying your needs; hard constraints are not silently relaxed.')
            else:
                def select_listing():
                    st.session_state.selected_listing = st.session_state['recommended-listing-selector']
                st.session_state['recommended-listing-selector'] = st.session_state.selected_listing
                st.selectbox('Recommended listings', eligible_ids, key='recommended-listing-selector', format_func=lambda value: f"{api.details(value).facts['displayTitle']} · {value}", on_change=select_listing)
                selected = st.session_state.selected_listing
                rec = next(r for r in recs if r.listing_id == selected)
                compact_details(api.details(selected), rec)
