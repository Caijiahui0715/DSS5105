"""The interface language (English by default, or Chinese) and the texts that depend on it."""
import re
import streamlit as st
from content.labels import VALUE_ZH

LANGUAGES = {'en': 'English', 'zh': '中文'}

# The backend's account and form messages, which are in English, for the Chinese interface.
BACKEND_ZH = {
    'Usernames are 3–20 letters, digits or underscores.': '用户名需为 3–20 个字母、数字或下划线。',
    'Passwords need at least 8 characters.': '密码至少 8 位。',
    'This username is already taken.': '这个用户名已被注册。',
    'Too many wrong passwords. Try again in a minute.': '密码错误次数过多，请 1 分钟后再试。',
    'Wrong username or password.': '用户名或密码不正确。',
    'Choose a faculty from the list.': '请从列表里选择学院。',
    'This listing is no longer in the data.': '找不到这套房源。',
    'Conversation not found.': '找不到这段对话。',
    'Type a message first.': '消息不能为空。',
    'That invite code is not right. Check it with whoever invited you.': '邀请码不对，请向管理员确认。',
    'Sign in first.': '请先登录。',
    'Long-term memory is off; switch it on to change the long-term profile.': '长期记忆已关闭，打开后才能修改长期资料。',
    'Long-term memory is off. Switch it on and save?': '长期记忆已关闭，要打开并保存吗？',
    'Long-term memory is off; switch it on to auto-save.': '长期记忆已关闭，打开后才能自动保存。',
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


def lease_label(months):
    """A lease length the forms offer: None for any, otherwise months."""
    if months is None:
        return t('Any lease length', '租期不限')
    if months % 12 == 0:
        years = months // 12
        return t(f'{years} year' + ('s' if years > 1 else ''), f'{years} 年')
    return t(f'{months} month' + ('s' if months > 1 else ''), f'{months} 个月')


def lease_term_label(term):
    """An advert's lease term ('1 year', 'Flexible'...), which the landlord treats as the shortest lease."""
    term = (term or '').strip()
    known = {'1 year': t('at least 1 year', '至少 1 年'), '2 years': t('at least 2 years', '至少 2 年'),
             'Flexible': t('flexible', '灵活'), 'Short Term': t('short term', '短租')}
    if term in ('', 'Prefer not to say'):
        return t('not stated', '未注明')
    return known.get(term, term)


def language_switch(key):
    """English / 中文. The choice lives in st.session_state.language, so pages without the
    switch keep it. Once chosen here, messages no longer switch it (follow_message)."""
    st.session_state[key] = language()
    st.radio(
        t('Language', '语言'), list(LANGUAGES), format_func=LANGUAGES.get, key=key, horizontal=True,
        label_visibility='collapsed',
        on_change=lambda: st.session_state.update({'language': st.session_state[key], 'language-chosen': True}),
    )


def message_language(text):
    """The language a message is written in, as the backend reads it to choose the reply's: 'zh',
    'en', or None for one that does not show it, such as "D05", "S010", "1500" or "ok"."""
    lowered = text.casefold()
    if any(phrase in lowered for phrase in ('用英文', '英文回答', '说英文', 'reply in english', 'respond in english')):
        return 'en'
    if any(phrase in lowered for phrase in ('用中文', '中文回答', '说中文', 'reply in chinese', 'respond in chinese')):
        return 'zh'
    if re.search(r'[\u4e00-\u9fff]', text):
        return 'zh'
    words = re.findall(r'[a-z]+', lowered)
    if not words or all(word in {'yes', 'no', 'ok', 'okay'} for word in words) or all(len(word) == 1 for word in words):
        return None
    return 'en'


def follow_message(text):
    """The interface follows the language the user writes in, as the replies do, until the user
    picks one with the switch."""
    written = message_language(text)
    if written and not st.session_state.get('language-chosen'):
        st.session_state.language = written


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
        return BACKEND_ZH.get(error.detail, error.detail) if language() == 'zh' else error.detail
    return str(error)
