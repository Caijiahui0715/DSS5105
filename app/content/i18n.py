"""The interface language (English by default, or Chinese) and the texts that depend on it."""
import streamlit as st
from content.labels import VALUE_ZH

LANGUAGES = {'en': 'English', 'zh': '中文'}

# The backend's account and form messages, for the English interface.
BACKEND_EN = {
    '用户名需为 3–20 个字母、数字或下划线。': 'Usernames are 3–20 letters, digits or underscores.',
    '密码至少 8 位。': 'Passwords need at least 8 characters.',
    '这个用户名已被注册。': 'This username is already taken.',
    '密码错误次数过多，请 1 分钟后再试。': 'Too many wrong passwords. Try again in a minute.',
    '用户名或密码不正确。': 'Wrong username or password.',
    '请从列表里选择学院。': 'Choose a faculty from the list.',
    '找不到这套房源。': 'This listing is no longer in the data.',
    '找不到这段对话。': 'This conversation no longer exists.',
    '消息不能为空。': 'Type a message first.',
}


def language():
    return st.session_state.get('language', 'en')


def t(en, zh):
    """The text in the interface language."""
    return zh if language() == 'zh' else en


def value_label(value):
    """A data value such as 'fully_furnished' in words."""
    if language() == 'zh' and value in VALUE_ZH:
        return VALUE_ZH[value]
    return str(value).replace('_', ' ').capitalize()


def language_switch(key):
    """English / 中文. The choice lives in st.session_state.language, so pages without the
    switch keep it."""
    st.session_state[key] = language()
    st.radio(
        t('Language', '语言'), list(LANGUAGES), format_func=LANGUAGES.get, key=key, horizontal=True,
        label_visibility='collapsed', on_change=lambda: st.session_state.update(language=st.session_state[key]),
    )


def describe(error):
    """A failed backend call in words, in the interface language."""
    from adapters.backend_client import BackendError, SessionExpired
    from adapters.configuration import backend_url

    if isinstance(error, SessionExpired):
        return t('Your sign-in has ended. Sign in again.', '登录已过期，请重新登录。')
    if isinstance(error, BackendError) and error.status is None:
        return t(
            f'Cannot reach the agent backend at {backend_url()}. Start it from the repository root with `uv run python server.py`, then reload this page.',
            f'连不上 agent 后端（{backend_url()}）。先在仓库根目录运行 `uv run python server.py`，再刷新本页。',
        )
    if isinstance(error, BackendError) and error.status == 504:
        return t('The agent backend took too long to answer; it may still be working on this conversation. Try again in a moment.',
                 '后端太久没有回应，可能还在处理这段对话，请稍后再试。')
    if isinstance(error, BackendError) and error.status >= 500:
        return t('The agent backend hit an error. Try again in a moment.', '后端出错了，请稍后再试。')
    if isinstance(error, BackendError):
        return BACKEND_EN.get(error.detail, error.detail) if language() == 'en' else error.detail
    return str(error)
