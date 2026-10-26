import re
import streamlit as st
from content.en import PRODUCT, TAGLINE
from content.i18n import t, language, language_switch, describe, value_label, lease_label
from domain.models import RentalRequirements, RentalPreferences
from domain.criteria import criteria_message, empty, form_changes
from state.session_store import current, start_session, faculties, refresh_new_conversations
from adapters.backend_client import BackendClient, BackendError
from adapters.configuration import offline, backend_url, demo_account
from adapters.http_rental_api import criteria_options

USERNAME = re.compile(r'[A-Za-z0-9_]{3,20}')  # the backend's rule (accounts.py)
MIN_PASSWORD = 8
SOFT_FIELDS = ('furnishing', 'private_bathroom', 'cooking', 'air_conditioning', 'pets', 'property_type')
LEASE_CHOICES = [None, 6, 12, 24]


def criteria_from_form(skip_preferences):
    """The sign-up form's hard requirements and soft preferences, or None when a hard one is missing."""
    budget = st.session_state.get('register-budget')
    scope = st.session_state.get('register-scope')
    bedrooms = st.session_state.get('register-bedrooms')
    if budget is None or budget <= 0 or scope not in ('room', 'entire_unit') or bedrooms is None:
        return None
    requirements = RentalRequirements(float(budget), scope, None if bedrooms == 'No minimum' else int(bedrooms), st.session_state.get('register-lease'))
    pref = RentalPreferences(districts=[], mrt_distance=None, commute_minutes=None)
    if not skip_preferences:
        pref.districts = list(st.session_state.get('register-districts', []))
        pref.mrt_distance = st.session_state.get('register-mrt')
        pref.commute_minutes = st.session_state.get('register-commute')
        for field in SOFT_FIELDS:
            setattr(pref, field, st.session_state.get(f'register-{field}', 'No preference'))
    return requirements, pref


def hard_requirements_error():
    return t('Complete all hard requirements: monthly budget, rental scope, and minimum bedroom choice. These cannot be skipped.',
             '请填写全部硬性条件：月租预算、租住方式和最少卧室数。这些不能跳过。')


def submit(mode, skip_preferences=False):
    # Callback executes before rerender: delete password widget state immediately.
    password = st.session_state.pop(f'{mode}-password', '')
    if not offline():
        # Only sign-up asks for the password twice.
        confirmation = st.session_state.pop('register-password-confirm', '') if mode == 'register' else password
        sign_in_to_backend(mode, password, confirmation, skip_preferences)
        return
    name = st.session_state.get(f'{mode}-name','').strip()
    email = st.session_state.get(f'{mode}-email','').strip()
    valid = bool(name and '@' in email and len(password) >= 6)
    del password
    error = None if valid else t('Enter your name, a valid email, and a password of at least six characters.', '请填写姓名、有效邮箱和至少 6 位的密码。')
    if mode == 'register':
        criteria = criteria_from_form(skip_preferences)
        if criteria is None:
            valid, error = False, hard_requirements_error()
        if valid:
            st.session_state.requirements, st.session_state.preferences = criteria
            conv = current()
            conv['requirements'], conv['preferences'] = criteria
            conv['recommendations'] = None
    st.session_state['auth-error'] = error
    forget_typed_password(mode, error)
    if valid:
        st.session_state.profile = {'name':name, 'email':email}
        st.session_state.authenticated = True
        st.session_state.page = 'Home'


def sign_in_to_backend(mode, password, confirmation, skip_preferences=False):
    """Signs in or creates the account on the backend; at sign-up the password is typed twice.
    The sign-up criteria become the first message to the agent, sent when Home opens."""
    username = st.session_state.get(f'{mode}-name', '').strip()
    criteria = criteria_from_form(skip_preferences) if mode == 'register' else None
    error = None
    if not USERNAME.fullmatch(username):
        error = t('Usernames are 3–20 letters, digits or underscores.', '用户名需为 3–20 个字母、数字或下划线。')
    elif len(password) < MIN_PASSWORD:
        error = t('Passwords need at least 8 characters.', '密码至少 8 位。')
    elif confirmation != password:
        error = t('The two passwords do not match. Type them again.', '两次输入的密码不一致，请重新输入。')
    elif mode == 'register' and criteria is None:
        error = hard_requirements_error()
    if error is None:
        client = BackendClient(backend_url())
        try:
            if mode == 'register':
                invite_code = st.session_state.get('register-invite', '').strip() or None
                account = client.register(username, password, st.session_state.get('register-faculty') or None, invite_code)
            else:
                account = client.sign_in(username, password)
            start_session(client, account)
        except BackendError as failure:
            error = describe(failure)
    del password, confirmation
    st.session_state['auth-error'] = error
    forget_typed_password(mode, error)
    if error is None:
        remember(client)
        if criteria is not None:
            keep_as_profile(client, criteria)
            st.session_state.pending_message = criteria_message(empty(), criteria, language(), first=True)


def keep_as_profile(client, criteria):
    """The sign-up criteria become the long-term profile, which switches long-term memory on: this
    and every later conversation start from them. If that fails, the first message still carries
    them to this conversation."""
    try:
        client.edit_profile(form_changes(empty(), criteria), via='signup')
        refresh_new_conversations()
    except BackendError:
        pass


def forget_typed_password(mode, error):
    # After a failed attempt the form stays on screen: clear the field there too, or the browser
    # sends the typed password back with the next rerun. After success the field is not rendered
    # again, so popping it (in submit) is enough.
    if error:
        st.session_state[f'{mode}-password'] = ''
        if mode == 'register' and not offline():
            st.session_state['register-password-confirm'] = ''


def remember(client):
    # Unticked: also forget a token an earlier sign-in left in this browser.
    st.session_state['cookie-action'] = client.token if st.session_state.get('remember-me', True) else 'delete'


def demo_sign_in():
    username, password = demo_account()
    client = BackendClient(backend_url())
    try:
        start_session(client, client.sign_in(username, password))
    except BackendError as failure:
        st.session_state['auth-error'] = describe(failure)
        return
    st.session_state['auth-error'] = None
    remember(client)


def form_choices():
    """Districts and property types for the sign-up form, from the backend or the offline files."""
    if offline():
        from data.source_loader import load_sources
        sources = load_sources()
        return ({d['district_code']:d['district'] for d in sources['districts']},
                sorted({listing.facts['propertyType'] for listing in sources['listings']}))
    options = criteria_options(backend_url())
    return {d['code']:d['name'] for d in options['districts']}, options['property_types']


def render():
    live = not offline()
    _, main, _ = st.columns([1,2,1])
    with main:
        language_switch('language-auth')
        st.caption(t('DSS5105 Student Project', 'DSS5105 课程项目') + ('' if live else t(' · Offline demo', ' · 离线演示')))
        st.title(PRODUCT)
        st.subheader(TAGLINE)
        if live:
            st.write(t('Describe what you need and the agent searches the current listings, checks their links and explains the trade-offs, with commute times to your faculty.',
                       '说出你的需求，agent 会搜索当前房源、检查链接并解释取舍，还会给出到你学院的通勤时间。'))
            st.info(t('Your account, conversations and favorites are kept by the agent backend. Use a password you do not use anywhere else.',
                      '账号、对话和收藏由 agent 后端保存。请用一个没在别处用过的密码。'))
        else:
            st.write(t('Make a more informed rental decision with real static listings, transparent trade-offs and a conversational demo.',
                       '用真实的静态房源、透明的取舍和对话演示，做出更有依据的租房决定。'))
            st.info(t('Demo authentication only. No identity verification or database persistence. Passwords are discarded on submission.',
                      '仅为演示登录：不验证身份，也不保存到数据库。提交后密码即被丢弃。'))
        login, register = st.tabs([t('Login', '登录'), t('Register', '注册')])
        for tab, mode in [(login,'login'),(register,'register')]:
            with tab:
                with st.form(f'{mode}-form', clear_on_submit=False):
                    st.text_input(t('Username', '用户名') if live else t('Name', '姓名'), key=f'{mode}-name')
                    if not live:
                        st.text_input(t('Email', '邮箱'), key=f'{mode}-email')
                    st.text_input(t('Password', '密码'), type='password', key=f'{mode}-password')
                    if live and mode == 'register':
                        st.text_input(t('Confirm password', '确认密码'), type='password', key='register-password-confirm')
                        if invite_code_required():
                            st.text_input(t('Invite code', '邀请码'), key='register-invite')
                    if mode == 'register':
                        if live:
                            faculty_choice()
                        criteria_fields(live)
                    if mode == 'login':
                        st.form_submit_button(t('Sign in', '登录'), on_click=submit, args=(mode,), type='primary')
                    else:
                        st.form_submit_button(t('Create account', '创建账号') if live else t('Create demo profile', '创建演示资料'), on_click=submit, args=(mode,), type='primary')
                        st.form_submit_button(t('Skip soft preferences and create account', '跳过偏好，直接创建账号') if live else t('Skip soft preferences and create profile', '跳过偏好，直接创建'), on_click=submit, args=(mode, True))
        if live:
            st.checkbox(t('Remember me on this device for 7 days', '在这台设备上保持登录 7 天'), value=True, key='remember-me')
        if st.session_state.get('auth-error'):
            st.error(st.session_state['auth-error'])
        if not live:
            if st.button(t('Continue with demo account', '使用演示账号'), width='stretch'):
                st.session_state.authenticated = True
                st.rerun()
        elif demo_account():
            st.button(t('Continue with demo account', '使用演示账号'), width='stretch', on_click=demo_sign_in)


def invite_code_required():
    """Whether the backend asks for an invite code at sign-up; a backend that cannot be reached
    shows its error elsewhere on the form."""
    try:
        return bool(criteria_options(backend_url()).get('invite_code_required'))
    except BackendError:
        return False


def faculty_choice():
    try:
        listed = faculties()
    except BackendError as failure:
        st.error(describe(failure))
        return
    names = {faculty['name']: faculty['zh'] if language() == 'zh' else faculty['name'] for faculty in listed}
    st.selectbox(t('Your NUS faculty (for commute times)', '你的 NUS 学院（用于计算通勤时间）'), list(names), index=None, key='register-faculty',
                 format_func=names.get, placeholder=t('Choose later in Profile if you prefer', '也可以以后在个人资料里选'))


def criteria_fields(live):
    st.subheader(t('Hard rental requirements · Required', '硬性条件 · 必填'))
    st.caption(t('Complete every field below. Hard requirements cannot be skipped.', '下面每一项都要填写，硬性条件不能跳过。'))
    if live:
        st.caption(t('What you fill in here is saved as your long-term profile, and every new conversation starts from it. You can change it, or switch long-term memory off, in Profile.',
                     '这里填的条件会存为你的长期资料，之后每个新对话都从它开始。可以在个人资料页修改，或关闭长期记忆。'))
    st.number_input(t('Maximum advertised monthly budget (SGD) *', '最高月租预算（新元）*'), min_value=1, value=None, step=100, key='register-budget', placeholder=t('Enter your monthly budget', '输入每月预算'))
    st.selectbox(t('Rental scope *', '租住方式 *'), ['room', 'entire_unit'], index=None, key='register-scope', placeholder=t('Choose a rental scope', '选择租住方式'),
                 format_func=lambda v: {'room':t('Shared accommodation / room', '合租单间'), 'entire_unit':t('Entire unit', '整租')}[v])
    st.selectbox(t('Minimum bedrooms *', '最少卧室数 *'), ['No minimum', *range(1, 21)], index=None, key='register-bedrooms',
                 placeholder=t('Choose a minimum or explicitly select No minimum', '选择数量，或明确选择“不限”'), format_func=lambda v: t('No minimum', '不限') if v == 'No minimum' else str(v))
    if live:
        # Adverts state the shortest lease they accept, so a short stay rules many out.
        st.selectbox(t('Lease length you will sign', '打算签多久的租约'), LEASE_CHOICES, key='register-lease', format_func=lease_label)
    with st.expander(t('Soft preferences · Optional', '偏好 · 选填')):
        st.caption(t('Leave these blank or skip them. You can update them later in Profile.', '可以留空或跳过，以后在个人资料里修改。'))
        try:
            districts, properties = form_choices()
        except BackendError as failure:
            st.error(describe(failure))
            return
        # The agent searches one district at a time.
        st.multiselect(t('Preferred district', '想住的区') if live else t('Preferred districts', '想住的区'), list(districts), key='register-districts',
                       format_func=lambda v:f'{v} · {districts[v]}', max_selections=1 if live else None)
        st.number_input(t('Preferred maximum MRT distance (m)', '离地铁站最远距离（米）'), min_value=100, value=None, key='register-mrt')
        st.number_input(t('Preferred maximum commute to your faculty (min)', '到学院的最长通勤时间（分钟）') if live else t('Preferred maximum NUS commute (min; demo estimate)', '到 NUS 的最长通勤时间（分钟，演示估计）'),
                        min_value=1, value=None, key='register-commute')
        options = {'property_type': ['No preference', *properties], 'furnishing':['No preference','fully_furnished','partially_furnished','unfurnished'], 'private_bathroom':['No preference','yes','no'], 'cooking':['No preference','allowed','light_only','not_allowed'], 'air_conditioning':['No preference','yes','no'], 'pets':['No preference','allowed','not_allowed']}
        for field, choices in options.items():
            st.selectbox(field_label(field), choices, key=f'register-{field}', format_func=choice_label)


def field_label(field):
    return {'property_type':t('Property type', '房产类型'), 'furnishing':t('Furnishing', '家具'), 'private_bathroom':t('Private bathroom', '独立卫浴'),
            'cooking':t('Cooking', '做饭'), 'air_conditioning':t('Air conditioning', '空调'), 'pets':t('Pets', '宠物')}[field]


def choice_label(value):
    return t('No preference', '不限') if value == 'No preference' else value_label(value)
