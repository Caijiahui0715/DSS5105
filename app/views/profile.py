from dataclasses import replace
import streamlit as st
from content.i18n import t, language, value_label, lease_label
from domain.criteria import criteria_message
from state.session_store import current, live, faculties


def choice_label(value):
    return t('No preference', '不限') if value == 'No preference' else value_label(value)


def render(api):
    st.title(t('Profile', '个人资料'))
    if live():
        st.caption(t('The agent keeps your search criteria. Changes here are sent to it as a message in the current conversation, so you can see what it understood.',
                     'agent 保存着你的找房条件。这里的修改会作为一条消息发到当前对话，你可以看到 agent 的理解。'))
        conv = current()
        req, pref = conv['requirements'], conv['preferences']
    else:
        st.caption(t('Changes are saved only in the active Streamlit session. Passwords are never stored.', '修改只保存在本次会话里，密码从不保存。'))
        req, pref = st.session_state.requirements, st.session_state.preferences
    district_codes = [d['district_code'] for d in api.sources['districts']]
    district_names = {d['district_code']:d['district'] for d in api.sources['districts']}
    # The values the form starts from; a field left as shown is not sent as a change.
    req = replace(req, max_budget=float(req.max_budget or 2500), min_bedrooms=None if req.min_bedrooms is None else min(20, req.min_bedrooms))
    pref = replace(pref, mrt_distance=None if pref.mrt_distance is None else max(100, pref.mrt_distance),
                   districts=[code for code in pref.districts if code in district_names])
    revision = st.session_state.get('profile-revision', 0)
    with st.form(f'profile-form-{revision}'):
        st.subheader(t('Personal information', '个人信息'))
        if live():
            st.write(t(f"Signed in as **{st.session_state.profile['name']}**", f"当前账号：**{st.session_state.profile['name']}**"))
            listed = {faculty['name']: faculty['zh'] if language() == 'zh' else faculty['name'] for faculty in faculties()}
            names = ['', *listed]
            saved = st.session_state.faculty if st.session_state.faculty in listed else ''
            faculty = st.selectbox(t('Your NUS faculty (commute times are to it)', '你的 NUS 学院（通勤时间按它计算）'), names, index=names.index(saved),
                                   format_func=lambda name: listed.get(name) or t('Not set', '未设置'))
        else:
            name = st.text_input(t('Name', '姓名'),st.session_state.profile['name'])
            email = st.text_input(t('Email', '邮箱'),st.session_state.profile['email'])
        st.subheader(t('Hard rental requirements', '硬性条件'))
        a,b,c = st.columns(3)
        budget = a.number_input(t('Maximum advertised monthly budget (SGD)', '最高月租预算（新元）'),min_value=1,value=int(req.max_budget))
        scopes = ['No requirement','room','entire_unit']
        scope = b.selectbox(t('Rental scope', '租住方式'),scopes,index=scopes.index(req.rental_scope or 'No requirement'),format_func=lambda v:{'room':t('Shared accommodation / room', '合租单间'),'entire_unit':t('Entire unit', '整租')}.get(v,t('No requirement', '不限')))
        bedroom_options = ['No minimum', *range(1, 21)]
        bedrooms = c.selectbox(t('Minimum bedrooms', '最少卧室数'), bedroom_options,
                              index=bedroom_options.index(req.min_bedrooms or 'No minimum'),
                              format_func=lambda v: t('No minimum', '不限') if v == 'No minimum' else str(v))
        if live():
            # The agent filters by each advert's shortest lease; a length saved in chat stays selectable.
            leases = list(dict.fromkeys([None, 6, 12, 24, req.lease_months]))
            lease = st.columns(3)[0].selectbox(t('Lease length you will sign', '打算签多久的租约'), leases, index=leases.index(req.lease_months), format_func=lease_label)
        st.subheader(t('Soft preferences', '偏好'))
        # The agent searches one district at a time.
        districts = st.multiselect(t('Preferred district', '想住的区') if live() else t('Preferred districts', '想住的区'),district_codes,default=pref.districts,
                                   format_func=lambda code:f'{code} · {district_names[code]}', max_selections=1 if live() else None)
        a,b = st.columns(2)
        mrt = a.number_input(t('Preferred maximum MRT distance (m)', '离地铁站最远距离（米）'),min_value=100,value=pref.mrt_distance)
        commute = b.number_input(t('Preferred maximum commute to your faculty (min)', '到学院的最长通勤时间（分钟）') if live() else t('Preferred maximum NUS commute (min; demo estimate)', '到 NUS 的最长通勤时间（分钟，演示估计）'),min_value=1,value=pref.commute_minutes)
        properties = ['No preference']+sorted({listing.facts['propertyType'] for listing in api.all_listings()} | ({pref.property_type} - {'No preference'}))
        property_type = st.selectbox(t('Preferred property type', '想要的房产类型'),properties,index=properties.index(pref.property_type),format_func=choice_label)
        options = {'furnishing':['No preference','fully_furnished','partially_furnished','unfurnished'], 'private_bathroom':['No preference','yes','no'],'cooking':['No preference','allowed','light_only','not_allowed'],'air_conditioning':['No preference','yes','no'],'pets':['No preference','allowed','not_allowed']}
        labels = {'furnishing':t('Furnishing', '家具'),'private_bathroom':t('Private bathroom', '独立卫浴'),'cooking':t('Cooking', '做饭'),'air_conditioning':t('Air conditioning', '空调'),'pets':t('Pets', '宠物')}
        values = {key:st.selectbox(labels[key],choices,index=choices.index(getattr(pref,key)),format_func=choice_label) for key,choices in options.items()}
        save,cancel = st.columns(2)
        submitted = save.form_submit_button(t('Save profile', '保存'),type='primary')
        canceled = cancel.form_submit_button(t('Cancel changes', '取消修改'))
    if submitted:
        new_req = replace(req,max_budget=float(budget),rental_scope=None if scope=='No requirement' else scope,min_bedrooms=None if bedrooms == 'No minimum' else int(bedrooms),
                          lease_months=lease if live() else req.lease_months)
        new_pref = replace(pref,districts=districts,mrt_distance=int(mrt) if mrt is not None else None,commute_minutes=int(commute) if commute is not None else None,property_type=property_type,**values)
        if live():
            save_to_agent(faculty or None, (req, pref), (new_req, new_pref))
        elif not name.strip() or '@' not in email:
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


def save_to_agent(faculty, shown, submitted):
    """A new faculty is saved to the account; changed criteria go to the agent as a message on Home."""
    notices = []
    if faculty != st.session_state.faculty:
        st.session_state.faculty = st.session_state.client.set_faculty(faculty)['faculty']
        notices.append(t('Faculty saved. Commute times now go to it.', '学院已保存，通勤时间按新学院计算。'))
    message = criteria_message(shown, submitted, language())
    if message:
        st.session_state.pending_message = message
        st.session_state.page = 'Home'
        notices.append(t('Your changes were sent to the agent.', '修改已发给 agent。'))
    st.session_state.notice = ' '.join(notices) or t('Nothing changed.', '没有改动。')
    st.session_state['profile-revision'] = st.session_state.get('profile-revision', 0) + 1
    st.rerun()
