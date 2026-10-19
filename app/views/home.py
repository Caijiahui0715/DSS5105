from datetime import datetime
import streamlit as st
from components.navigation import conversation_sidebar
from components.map_view import map_view
from components.listing_details import compact_details
from components.criteria_panel import criteria_form, drop_message, label, other_criteria
from content.en import PROMPTS, PROMPTS_ZH
from content.i18n import t, language, describe
from domain.criteria import criteria_message
from state.session_store import current, live, waiting_for_reply, refresh_new_conversations, NEW_TITLE
from adapters.backend_client import SessionExpired
from domain.models import ApiError


def as_markdown(text):
    """Chat text as Streamlit shows it: "S$" amounts are not LaTeX, and each line stays a line
    (the agent puts every listing fact on its own line; markdown would join them)."""
    return text.replace('$', '\\$').replace('\n', '  \n')


def send(message, agent, thread):
    """One message to the agent. The message shows at once in the thread, with the agent's progress under it."""
    conv = current()
    with thread:
        with st.container(key=f"chat-user-{len(conv['messages'])}"):
            with st.chat_message('user'):
                st.markdown(as_markdown(message))
        try:
            if live():
                # Read the conversation from the backend again unless this run sees the reply through:
                # a click while the agent works restarts the page, and the backend still finishes the turn.
                conv['loaded'] = False
                with st.status(t('Working on your request…', '正在处理你的请求…')) as status:
                    response = agent.respond(conv, message, language(), lambda text: status.update(label=text))
                    status.update(label=t('Done', '完成'), state='complete')
            else:
                with st.spinner(t('Searching static listings…', '正在搜索静态房源…')):
                    response = agent.respond(message, conv['requirements'], conv['preferences'], conv['messages'])
        except SessionExpired:
            raise
        except ApiError as exc:
            # The backend may have kept the message anyway; the conversation is read from it again.
            st.error(describe(exc))
            return
    conv['messages'].extend([{'role': 'user', 'text': message}, {'role': 'assistant', 'text': response.text, 'clarification': response.clarification, 'steps': response.steps}])
    if conv['title'] in ('', NEW_TITLE):
        conv['title'] = message[:55]
    conv['requirements'], conv['preferences'] = response.requirements, response.preferences
    # A turn without a search keeps the listings already in the panel.
    if response.recommendations is not None:
        conv['recommendations'], conv['preview'] = response.recommendations, response.preview
        st.session_state.selected_listing = response.recommendations[0].listing_id if response.recommendations else None
    if response.shortlist is not None:
        st.session_state.shortlist = response.shortlist
    if response.criteria is not None:
        conv['criteria'] = response.criteria
    conv['updated'] = datetime.now().isoformat(timespec='seconds')
    conv['loaded'] = True
    st.rerun()


def ask(message):
    """A criteria change from the panel, sent to the agent like a typed message."""
    if message:
        st.session_state.pending_message = message
    else:
        st.session_state.notice = t('Nothing changed.', '没有改动。')
    st.rerun()


def criteria_panel(api):
    """This conversation's criteria above its listings. Changes go to the agent as a message and stay
    in this conversation; saving them to the long-term profile is a separate step."""
    conv = current()
    # What this conversation changed that the long-term profile does not have yet, as of the last
    # reply; shown above the panel so it is seen while the panel is closed.
    if unsaved := conv['criteria'].get('profile_changes'):
        names = ('、' if language() == 'zh' else ', ').join(row['label'][language()] for row in unsaved)
        st.caption(t(f"{len(unsaved)} change{'s' if len(unsaved) > 1 else ''} not saved to your long-term profile ({names}); save it below.",
                     f"有 {len(unsaved)} 项改动还没存到长期资料（{names}），可以在下面保存。"))
    with st.expander(t("This conversation's criteria", '本次对话的条件'), icon=':material/tune:'):
        st.caption(t('Changes here are sent to the agent as a message. They stay in this conversation until you save them to your long-term profile.',
                     '这里的修改会作为一条消息发给 agent，只改这段对话；存为长期资料后，长期资料才会跟着改。'))
        busy = waiting_for_reply(conv)
        criteria_form(api, conv['criteria'], 'conversation', t('Send the changes to the agent', '把修改发给 agent'),
                      lambda before, after: ask(criteria_message(before, after, language())), disabled=busy)
        other_criteria(conv['criteria'], 'conversation', lambda item: ask(drop_message(item)), disabled=busy)
        st.divider()
        save_controls(conv)


def save_controls(conv):
    """Save this conversation's criteria to the long-term profile, after seeing what that changes."""
    client = st.session_state.client
    if conv['thread_id'] is None:
        st.caption(t('Once the conversation starts, its criteria can be saved to your long-term profile.', '对话开始后，可以把它的条件存为长期资料。'))
        return
    key = f"profile-preview-{conv['thread_id']}"
    if st.button(t('Save to long-term profile', '存为长期资料'), icon=':material/bookmark_add:', key='save-profile-preview'):
        st.session_state[key] = client.profile_changes(conv['thread_id'])
    preview = st.session_state.get(key)
    if not preview:
        return
    lang = language()
    if not preview['changes']:
        st.info(t('Your long-term profile already has these criteria; nothing to save.', '长期资料里已经是这些条件，没有要保存的改动。'))
        del st.session_state[key]
        return
    st.markdown(t('**Saving changes your long-term profile like this:**', '**保存后，长期资料会这样改：**'))
    st.markdown('\n'.join(f"- {label(row)}{'：' if lang == 'zh' else ': '}{row['before'][lang]} → {row['after'][lang]}" for row in preview['changes']))
    off = preview['memory'] == 'off'
    if off:
        st.warning(t('Long-term memory is off. Switch it on and save?', '长期记忆已关闭，要打开并保存吗？'))
    confirm, cancel = st.columns(2)
    if confirm.button(t('Switch on and save', '打开并保存') if off else t('Save', '确认保存'), type='primary', key='save-profile-confirm'):
        client.save_profile(conv['thread_id'], switch_on=off)
        del st.session_state[key]
        conv['criteria'] = {**conv['criteria'], 'profile_changes': []}
        refresh_new_conversations()
        st.session_state.notice = t('Saved to your long-term profile. New conversations start from it.', '已存为长期资料，新对话会按它开始。')
        st.rerun()
    if cancel.button(t('Cancel', '取消'), key='save-profile-cancel'):
        del st.session_state[key]
        st.rerun()


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
            if st.button(t('Toggle conversation history', '显示或隐藏对话记录'), icon=':material/menu:', help=t('Show or hide conversation history', '显示或隐藏对话记录'), key='toggle-history'):
                st.session_state.history_open = not st.session_state.get('history_open', True)
                st.rerun()
        thread = st.container(height=580, border=False, key='chat-thread')
        with thread:
            if not conv['messages']:
                st.markdown(t('## How can I help with your rental search?', '## 想找什么样的房子？'))
            for index, message in enumerate(conv['messages']):
                with st.container(key=f"chat-{message['role']}-{index}"):
                    with st.chat_message(message['role']):
                        st.markdown(as_markdown(message['text']))
                        if message.get('clarification'):
                            st.warning(message['clarification'])
                        if message.get('steps'):
                            with st.expander(t('How this reply was made', '这条回复是怎么得出的')):
                                st.markdown('\n'.join(f'- {as_markdown(step)}' for step in message['steps']))
            if live() and waiting_for_reply(conv):
                st.info(t('No reply to this message yet. If the agent is still working on it, the reply appears after a refresh; otherwise send it again.',
                          '这条消息还没有回复。如果 agent 还在处理，刷新后就会显示；否则请重新发送。'))
                st.button(t('Refresh', '刷新'), key='refresh-reply')
        if message := st.chat_input(t('Message the rental Agent', '给找房 agent 发消息'), key='rental-chat-input'):
            send(message, agent, thread)
        # Criteria from sign-up or Profile, sent as a message once Home is open.
        elif pending := st.session_state.pop('pending_message', None):
            send(pending, agent, thread)
    with right:
        if live():
            criteria_panel(api)
        # The map fills its panel: 350px high with a 1px border (see streamlit_app.py).
        with st.container(height=350, border=True, key='map-panel'):
            map_view(api, key='home-map', height=348, listing_ids=eligible_ids, compact=True)
        with st.container(height=420, border=True, key='listing-panel'):
            if not recs:
                st.caption(t('Your recommended listings will appear here.', '推荐的房源会显示在这里。'))
                st.markdown(t('**Try a rental request**', '**试试这样问**'))
                for i, prompt in enumerate(PROMPTS_ZH if language() == 'zh' else PROMPTS):
                    if st.button(prompt, key=f'prompt-{i}', width='stretch'):
                        send(prompt, agent, thread)
                if conv['recommendations'] == []:
                    st.caption(t('No recommended listings for this request. Try clarifying your needs; hard constraints are not silently relaxed.',
                                 '这次没有推荐的房源。可以把需求说得更具体；硬性条件不会被悄悄放宽。'))
            else:
                if conv.get('preview'):
                    st.caption(t('Preview only: your saved criteria have not changed.', '仅为预览：你保存的条件没有改变。'))
                index = {rec.listing_id: rec for rec in recs}
                def select_listing():
                    st.session_state.selected_listing = st.session_state['recommended-listing-selector']
                def label(value):
                    title = index[value].facts.get('title') or api.details(value).facts['displayTitle']
                    return f'#{index[value].rank} · {title} · {value}'
                st.session_state['recommended-listing-selector'] = st.session_state.selected_listing
                st.selectbox(t('Recommended listings', '推荐的房源'), eligible_ids, key='recommended-listing-selector', format_func=label, on_change=select_listing)
                selected = st.session_state.selected_listing
                compact_details(api.details(selected), index[selected])
