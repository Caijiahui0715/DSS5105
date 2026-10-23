import streamlit as st
from adapters.backend_client import BackendError
from content.i18n import t, language_switch, describe
from domain.models import ApiError
from state.session_store import navigate, new_conversation, logout, title, live, busy, delete_conversation, replying, replied, stop_waiting


def navigation(compact=False):
    """Three persistent native-widget destinations; CSS fixes the icon rail."""
    labels = {'Home': t('Home', '首页'), 'Favorites': t('Favorites', '收藏'), 'Profile': t('Profile', '个人资料')}
    with st.container(key='global-rail'):
        for page, icon in [('Home', 'home'), ('Favorites', 'bookmark'), ('Profile', 'person')]:
            if st.button(labels[page], icon=f':material/{icon}:', help=labels[page], key=f'nav-{page}', width='stretch', type='primary' if st.session_state.page == page else 'secondary'):
                navigate(page)


# The history is drawn after the page, so its buttons act before the run that draws it.
def open_conversation(key):
    st.session_state.active_conversation = key
    recs = st.session_state.conversations[key]['recommendations'] or []
    st.session_state.selected_listing = recs[0].listing_id if recs else None


def start_conversation():
    new_conversation()
    st.session_state.selected_listing = None


def confirm_delete(key):
    """Asks before deleting a conversation, naming it: deleting cannot be undone."""
    conv = st.session_state.conversations[key]
    if busy(conv):
        # A click from before the agent started replying: not while it replies.
        st.session_state.notice = t('Delete once the reply has arrived.', '回复完成后才能删除。')
        return

    def body():
        st.write(t(f'Delete the conversation “{title(conv)}”? This cannot be undone.', f'删除对话「{title(conv)}」？删除后无法恢复。'))
        st.caption(t('Your long-term profile, favorites, exclusions and faculty stay.', '长期资料、收藏、排除和学院都不受影响。'))
        delete, cancel = st.columns(2)
        if delete.button(t('Delete', '删除'), type='primary', key='delete-conversation-confirm', width='stretch'):
            try:
                delete_conversation(key)
            except ApiError as error:
                st.error(describe(error))
                return
            st.rerun()
        if cancel.button(t('Cancel', '取消'), key='delete-conversation-cancel', width='stretch'):
            st.rerun()

    st.dialog(t('Delete conversation', '删除对话'))(body)()


def watch_replies(keys):
    """Conversations left while the agent replied (keys): ask the backend every 2 seconds whether
    each reply is there, and draw the history again once one is. Home watches the open one."""
    @st.fragment(run_every=2)
    def check():
        arrived = False
        for key in keys:
            conv = st.session_state.conversations.get(key)
            if conv is None or not replying(conv):
                continue
            try:
                messages = st.session_state.client.messages(conv['thread_id'])
            except BackendError:
                continue  # Asked again in 2 seconds.
            if replied(conv, messages):
                stop_waiting(conv)
                conv['loaded'] = False  # opened, it shows the reply
                arrived = True
        if arrived:
            st.rerun()

    check()


def conversation_sidebar():
    with st.container(key='chat-history'):
        st.button(t('Hide conversation history', '收起对话记录'), icon=':material/left_panel_close:', key='close-history', width='stretch',
                  on_click=lambda: st.session_state.update(history_open=False))
        st.markdown(t('### Your conversations', '### 你的对话'))
        st.button(t('New conversation', '新对话'), icon=':material/edit_square:', key='new-chat', width='stretch', on_click=start_conversation)
        with st.container(key='history-heading'):
            st.caption(t('History', '历史对话'))
            st.divider()
        for key, conv in reversed(list(st.session_state.conversations.items())):
            active = key == st.session_state.active_conversation
            # A spinner while the agent replies in it, also once the page has left it.
            row = dict(key=f'recent-{key}', width='stretch', on_click=open_conversation, args=(key,), icon='spinner' if replying(conv) else None)
            # The open conversation, once started, has a delete button on its row. The row never
            # wraps: a long title is cut short instead of pushing the button below it.
            if active and live() and conv['thread_id']:
                with st.container(key='open-conversation', horizontal=True, wrap=False, vertical_alignment='center', gap='small'):
                    st.button(title(conv), type='primary', **row)
                    working = busy(conv)
                    if st.button(t('Delete this conversation', '删除这段对话'), icon=':material/delete:', key='delete-conversation', disabled=working,
                                 help=t('Delete once the reply has arrived', '回复完成后才能删除') if working else t('Delete this conversation', '删除这段对话')):
                        confirm_delete(key)
            else:
                st.button(title(conv), type='primary' if active else 'secondary', **row)
        st.divider()
        language_switch('language-sidebar')
        st.caption(st.session_state.profile['name'])
        if st.button(t('Log out', '退出登录'), icon=':material/logout:'):
            logout()
        away = [key for key, conv in st.session_state.conversations.items() if key != st.session_state.active_conversation and replying(conv)]
        if away:
            watch_replies(away)
