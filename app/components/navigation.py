import streamlit as st
from content.i18n import t, language_switch
from state.session_store import navigate, new_conversation, logout, live, title


def navigation(compact=False):
    """Three persistent native-widget destinations; CSS fixes the icon rail."""
    labels = {'Home': t('Home', '首页'), 'Favorites': t('Favorites', '收藏'), 'Profile': t('Profile', '个人资料')}
    with st.container(key='global-rail'):
        for page, icon in [('Home', 'home'), ('Favorites', 'bookmark'), ('Profile', 'person')]:
            if st.button(labels[page], icon=f':material/{icon}:', help=labels[page], key=f'nav-{page}', width='stretch', type='primary' if st.session_state.page == page else 'secondary'):
                navigate(page)


def open_conversation(key):
    st.session_state.active_conversation = key
    recs = st.session_state.conversations[key]['recommendations'] or []
    st.session_state.selected_listing = recs[0].listing_id if recs else None
    st.rerun()


def conversation_sidebar():
    with st.container(key='chat-history'):
        if st.button(t('Hide conversation history', '收起对话记录'), icon=':material/left_panel_close:', key='close-history'):
            st.session_state.history_open = False
            st.rerun()
        st.markdown(t('### Your conversations', '### 你的对话'))
        if st.button(t('New conversation', '新对话'), icon=':material/edit_square:', key='new-chat', width='stretch'):
            new_conversation()
            st.session_state.selected_listing = None
            st.rerun()
        st.caption(t('Saved to your account', '已保存到你的账号') if live() else t('Current session', '本次会话'))
        for key, conv in reversed(list(st.session_state.conversations.items())):
            if st.button(title(conv), key=f'recent-{key}', width='stretch', type='primary' if key == st.session_state.active_conversation else 'secondary'):
                open_conversation(key)
        st.divider()
        if live():
            st.caption(t('Conversations and favorites stay with your account.', '对话和收藏会保存在你的账号里。'))
        else:
            st.caption(t('History and saved listings last for this session only.', '对话记录和收藏只在本次会话中保留。'))
        language_switch('language-sidebar')
        st.caption(st.session_state.profile['name'])
        if st.button(t('Log out', '退出登录'), icon=':material/logout:'):
            logout()
