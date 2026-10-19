from dataclasses import replace
import streamlit as st
from components.criteria_panel import criteria_form, other_criteria
from content.i18n import t, language, value_label
from domain.criteria import form_changes
from state.session_store import current, live, faculties, logout, refresh_new_conversations


def choice_label(value):
    return t('No preference', '不限') if value == 'No preference' else value_label(value)


def render(api):
    st.title(t('Profile', '个人资料'))
    if live():
        render_account(api)
    else:
        render_demo(api)


def render_account(api):
    """Signed in: the account, the long-term profile with its memory switch, excluded listings, and
    deleting everything."""
    client = st.session_state.client
    st.write(t(f"Signed in as **{st.session_state.profile['name']}**", f"当前账号：**{st.session_state.profile['name']}**"))
    faculty_setting()
    st.divider()
    long_term_profile(api, client.profile())
    st.divider()
    excluded_listings(api)
    st.divider()
    delete_everything()


def faculty_setting():
    listed = {faculty['name']: faculty['zh'] if language() == 'zh' else faculty['name'] for faculty in faculties()}
    names = ['', *listed]
    # Set before the widget is drawn, so it shows the saved faculty.
    st.session_state['faculty-setting'] = st.session_state.faculty if st.session_state.faculty in listed else ''

    def change():
        st.session_state.faculty = st.session_state.client.set_faculty(st.session_state['faculty-setting'] or None)['faculty']
        st.session_state.notice = t('Faculty saved. Commute times now go to it.', '学院已保存，通勤时间按新学院计算。')

    st.selectbox(t('Your NUS faculty (commute times are to it)', '你的 NUS 学院（通勤时间按它计算）'), names, key='faculty-setting',
                 format_func=lambda name: listed.get(name) or t('Not set', '未设置'), on_change=change)


def long_term_profile(api, profile):
    client = st.session_state.client
    st.subheader(t('Long-term profile', '长期资料'))
    st.caption(t('While long-term memory is on, every new conversation starts from these criteria. What you change in a conversation stays there until you save it here.',
                 '长期记忆打开时，每个新对话都会按这些条件开始。对话里改的条件只属于那段对话，存为长期资料后才会改到这里。'))
    memory = profile['memory']
    st.session_state['memory-switch'] = memory == 'on'

    def switch():
        on = st.session_state['memory-switch']
        client.set_memory(on)
        refresh_new_conversations()
        st.session_state.notice = (t('Long-term memory is on: new conversations start from your long-term profile.', '长期记忆已打开，新对话会按长期资料开始。') if on
                                   else t('Long-term memory is off: what is saved stays, but new conversations do not use it.', '长期记忆已关闭：保存的内容还在，但新对话不会使用。'))

    st.toggle(t('Long-term memory', '长期记忆'), key='memory-switch', on_change=switch)
    if profile['saved_on']:
        st.caption(t(f"Last saved {profile['saved_on']}", f"最后保存 {profile['saved_on']}"))
    if memory == 'off':
        st.info(t('Long-term memory is off: the saved criteria stay, but new conversations do not use them and they cannot be changed. Switch it on to edit them.',
                  '长期记忆已关闭：保存的条件还在，但新对话不会使用，也不能修改。打开后才能编辑。'))
    elif memory == 'undecided':
        st.caption(t('Nothing is saved yet. Saving here also switches long-term memory on.', '还没有保存过。在这里保存会同时打开长期记忆。'))
    if (budget := profile.get('budget')) and memory != 'off':
        st.caption(t(f"The budget was saved as you said it, {budget['amount']:,} {budget['currency']}" + (f" for {budget['months']} months" if budget.get('months', 1) > 1 else '')
                     + ", and is worked out again at the day's rate for each new conversation. A budget typed here is a monthly amount in SGD.",
                     f"预算按你说的 {budget['amount']:,} {budget['currency']}" + (f"（{budget['months']} 个月）" if budget.get('months', 1) > 1 else '')
                     + " 保存，每个新对话按当天汇率重新换算。在这里填的预算是每月新元金额。"))
    saved = {key: profile[key] for key in ('preferences', 'sources', 'items')}
    off = memory == 'off'

    def save(before, after):
        changes = form_changes(before, after)
        if changes:
            client.edit_profile(changes)
            refresh_new_conversations()
        st.session_state.notice = t('Saved to your long-term profile.', '已保存到长期资料。') if changes else t('Nothing changed.', '没有改动。')
        st.rerun()

    def drop(item):
        client.edit_profile({item['field']: None})
        refresh_new_conversations()
        st.session_state.notice = t(f"Dropped “{item['label']['en']}”.", f"已去掉“{item['label']['zh']}”。")
        st.rerun()

    criteria_form(api, saved, 'profile', t('Save to long-term profile', '保存到长期资料'), save, disabled=off)
    other_criteria(saved, 'profile', drop, disabled=off)
    if not profile['preferences']:
        return
    if st.button(t('Delete long-term profile', '删除长期资料'), icon=':material/delete:', key='delete-profile'):
        st.session_state['confirm-delete-profile'] = True
    if st.session_state.get('confirm-delete-profile'):
        st.warning(t('This deletes the saved criteria. The memory switch, favorites and exclusions stay.', '这会删除保存的条件；长期记忆开关、收藏和排除都不变。'))
        confirm, cancel = st.columns(2)
        if confirm.button(t('Delete', '确认删除'), type='primary', key='delete-profile-confirm'):
            client.delete_profile()
            refresh_new_conversations()
            st.session_state['confirm-delete-profile'] = False
            st.session_state.notice = t('Long-term profile deleted.', '长期资料已删除。')
            st.rerun()
        if cancel.button(t('Cancel', '取消'), key='delete-profile-cancel'):
            st.session_state['confirm-delete-profile'] = False
            st.rerun()


def excluded_listings(api):
    st.subheader(t('Excluded listings', '已排除的房源'))
    # Read again: the agent may have excluded listings in any conversation.
    listings = st.session_state.client.my_listings()
    st.session_state.shortlist, st.session_state.excluded = listings['shortlist'], listings['excluded']
    excluded = listings['excluded']
    if not excluded:
        st.caption(t('None. Say “not this one” in a conversation and later searches leave that listing out.', '没有。在对话里说“不要这套”，之后的搜索就不再显示它。'))
        return
    st.caption(t('Searches in every conversation leave these out.', '所有对话的搜索都不会显示这些房源。'))
    for listing_id in excluded:
        listing = api.details(listing_id)
        text, restore = st.columns([5, 1], vertical_alignment='center')
        text.write(f"{listing.facts['displayTitle'] if listing else t('No longer in the data', '已不在数据中')} · {listing_id}")
        if restore.button(t('Restore', '恢复'), key=f'restore-{listing_id}'):
            listings = st.session_state.client.restore(listing_id)
            st.session_state.shortlist, st.session_state.excluded = listings['shortlist'], listings['excluded']
            st.session_state.notice = t(f'{listing_id} will show in searches again.', f'{listing_id} 会重新出现在搜索结果里。')
            st.rerun()


def delete_everything():
    st.subheader(t('Delete all my data', '删除我的全部数据'))
    st.caption(t('Deletes every conversation, your long-term profile, favorites, exclusions and faculty, and signs you out on every device. Your account stays, so you can sign in again.',
                 '会删除所有对话、长期资料、收藏、排除和学院，并在所有设备上退出登录。账号本身保留，可以重新登录。'))
    sure = st.checkbox(t('I understand this cannot be undone', '我确定，删除后无法恢复'), key='delete-all-sure')
    if st.button(t('Delete all my data', '删除我的全部数据'), icon=':material/delete_forever:', key='delete-all', disabled=not sure):
        st.session_state.client.delete_my_data()
        logout()


def render_demo(api):
    """The offline demo: criteria kept in this Streamlit session only."""
    st.caption(t('Changes are saved only in the active Streamlit session. Passwords are never stored.', '修改只保存在本次会话里，密码从不保存。'))
    req, pref = st.session_state.requirements, st.session_state.preferences
    district_codes = [d['district_code'] for d in api.sources['districts']]
    district_names = {d['district_code']:d['district'] for d in api.sources['districts']}
    # The values the form starts from.
    req = replace(req, max_budget=float(req.max_budget or 2500), min_bedrooms=None if req.min_bedrooms is None else min(20, req.min_bedrooms))
    pref = replace(pref, mrt_distance=None if pref.mrt_distance is None else max(100, pref.mrt_distance),
                   districts=[code for code in pref.districts if code in district_names])
    revision = st.session_state.get('profile-revision', 0)
    with st.form(f'profile-form-{revision}'):
        st.subheader(t('Personal information', '个人信息'))
        name = st.text_input(t('Name', '姓名'),st.session_state.profile['name'])
        email = st.text_input(t('Email', '邮箱'),st.session_state.profile['email'])
        st.subheader(t('Hard rental requirements', '硬性条件'))
        a,b,c = st.columns(3)
        budget = a.number_input(t('Maximum advertised monthly budget (SGD)', '最高月租预算（新元）'),min_value=1,value=int(req.max_budget))
        scopes = ['No requirement','room','entire_unit']
        scope = b.selectbox(t('Rental scope', '租住方式'),scopes,index=scopes.index(req.rental_scope or 'No requirement'),format_func=lambda v:{'room':t('Shared accommodation / room', '合租单间'),'entire_unit':t('Entire unit', '整租')}.get(v,t('No requirement', '不限')))
        bed_required = c.checkbox(t('Require a minimum bedroom count', '要求最少卧室数'),value=req.min_bedrooms is not None)
        bedrooms = c.number_input(t('Minimum bedrooms', '最少卧室数'),min_value=0,max_value=20,value=req.min_bedrooms or 0)
        st.subheader(t('Soft preferences', '偏好'))
        districts = st.multiselect(t('Preferred districts', '想住的区'),district_codes,default=pref.districts,
                                   format_func=lambda code:f'{code} · {district_names[code]}')
        a,b = st.columns(2)
        mrt = a.number_input(t('Preferred maximum MRT distance (m)', '离地铁站最远距离（米）'),min_value=100,value=pref.mrt_distance)
        commute = b.number_input(t('Preferred maximum NUS commute (min; demo estimate)', '到 NUS 的最长通勤时间（分钟，演示估计）'),min_value=1,value=pref.commute_minutes)
        properties = ['No preference']+sorted({listing.facts['propertyType'] for listing in api.all_listings()} | ({pref.property_type} - {'No preference'}))
        property_type = st.selectbox(t('Preferred property type', '想要的房产类型'),properties,index=properties.index(pref.property_type),format_func=choice_label)
        options = {'furnishing':['No preference','fully_furnished','partially_furnished','unfurnished'], 'private_bathroom':['No preference','yes','no'],'cooking':['No preference','allowed','light_only','not_allowed'],'air_conditioning':['No preference','yes','no'],'pets':['No preference','allowed','not_allowed']}
        labels = {'furnishing':t('Furnishing', '家具'),'private_bathroom':t('Private bathroom', '独立卫浴'),'cooking':t('Cooking', '做饭'),'air_conditioning':t('Air conditioning', '空调'),'pets':t('Pets', '宠物')}
        values = {key:st.selectbox(labels[key],choices,index=choices.index(getattr(pref,key)),format_func=choice_label) for key,choices in options.items()}
        save,cancel = st.columns(2)
        submitted = save.form_submit_button(t('Save profile', '保存'),type='primary')
        canceled = cancel.form_submit_button(t('Cancel changes', '取消修改'))
    if submitted:
        new_req = replace(req,max_budget=float(budget),rental_scope=None if scope=='No requirement' else scope,min_bedrooms=int(bedrooms) if bed_required else None)
        new_pref = replace(pref,districts=districts,mrt_distance=int(mrt) if mrt is not None else None,commute_minutes=int(commute) if commute is not None else None,property_type=property_type,**values)
        if not name.strip() or '@' not in email:
            st.error(t('Provide your name and a valid email.', '请填写姓名和有效邮箱。'))
        else:
            st.session_state.profile = {'name':name.strip(),'email':email.strip()}
            st.session_state.requirements, st.session_state.preferences = new_req, new_pref
            conv = current()
            conv['requirements'],conv['preferences'] = st.session_state.requirements,st.session_state.preferences
            conv['recommendations'] = api.recommendations(conv['requirements'],conv['preferences'])
            st.session_state.notice = t('Profile saved for this session. Recommendations updated.', '已保存（仅本次会话），推荐已更新。')
            st.session_state['profile-revision'] = revision + 1
            st.rerun()
    if canceled:
        st.session_state['profile-revision'] = revision + 1
        st.rerun()
