"""The criteria form shared by the Profile page (the long-term profile) and Home (this conversation's
criteria): the common criteria as fields, "any" when not set, with where each value came from under it,
and every other saved criterion listed apart with a button to drop it."""
from dataclasses import replace
import streamlit as st
from content.i18n import t, language, value_label, lease_label
from domain.criteria import FORM_FIELDS, from_backend, in_form

NO = 'No preference'
_OPTIONS = {
    'furnishing': ['No preference', 'fully_furnished', 'partially_furnished', 'unfurnished'],
    'private_bathroom': ['No preference', 'yes', 'no'],
    'cooking': ['No preference', 'allowed', 'light_only', 'not_allowed'],
    'air_conditioning': ['No preference', 'yes', 'no'],
    'pets': ['No preference', 'allowed', 'not_allowed'],
}


def source_text(source):
    """Where a saved criterion came from, in a few words; None when unknown."""
    if not source:
        return None
    day = (source.get('date') or '')[5:]
    if source.get('via') == 'profile':
        return t(f'Changed on the Profile page on {day}', f'{day} 在个人资料页修改')
    quote = source.get('quote') or ''
    if quote:
        quote = quote if len(quote) <= 40 else quote[:39] + '…'
        return t(f'From what you said on {day}: “{quote}”', f'来自你 {day} 说的“{quote}”')
    return t(f'Saved on {day}', f'{day} 保存')


def label(item):
    """A criterion's label from the backend in the interface language, as the start of a line."""
    text = item['label'][language()]
    return text[:1].upper() + text[1:]


def criteria_form(api, saved, key, submit_label, on_submit, disabled=False):
    """saved: {'preferences', 'sources', 'items'} from the backend. on_submit(before, after) gets the
    form's values before and after, each a (requirements, preferences) pair, when it is submitted."""
    requirements, preferences = from_backend(saved['preferences'])
    shown = in_form(saved['preferences'])
    sources = saved.get('sources') or {}

    def source(column, field):
        found = next((sources[name] for name in FORM_FIELDS[field] if name in shown and name in sources), None)
        if text := source_text(found):
            column.caption(text)

    district_names = {d['district_code']: d['district'] for d in api.sources['districts']}
    districts = [None, *district_names]
    district = next((code for code in preferences.districts if code in district_names), None)
    properties = [NO, *sorted({listing.facts['propertyType'] for listing in api.all_listings()} | ({preferences.property_type} - {NO}))]
    any_label = t('Any', '不限')
    revision = st.session_state.get(f'{key}-revision', 0)
    with st.form(f'{key}-form-{revision}', border=False):
        a, b, c = st.columns(3)
        budget = a.number_input(t('Maximum monthly rent (SGD)', '最高月租（新元）'), min_value=1, step=50, placeholder=any_label, disabled=disabled,
                                value=None if requirements.max_budget is None else int(requirements.max_budget))
        source(a, 'max_budget')
        scopes = [None, 'room', 'entire_unit']
        scope = b.selectbox(t('Rental scope', '租住方式'), scopes, index=scopes.index(requirements.rental_scope), disabled=disabled,
                            format_func=lambda v: {'room': t('Room in a shared home', '合租单间'), 'entire_unit': t('Entire unit', '整租')}.get(v, any_label))
        source(b, 'rental_scope')
        # As on the sign-up form; a count saved in chat outside 1-20 stays selectable.
        counts = list(dict.fromkeys([None, *range(1, 21), requirements.min_bedrooms]))
        bedrooms = c.selectbox(t('Minimum bedrooms', '最少卧室数'), counts, index=counts.index(requirements.min_bedrooms), disabled=disabled,
                               format_func=lambda v: t('No minimum', '不限') if v is None else str(v))
        source(c, 'min_bedrooms')
        a, b, c = st.columns(3)
        # The agent filters by each advert's shortest lease; a length saved in chat stays selectable.
        leases = list(dict.fromkeys([None, 6, 12, 24, requirements.lease_months]))
        lease = a.selectbox(t('Lease length you will sign', '打算签多久的租约'), leases, index=leases.index(requirements.lease_months), format_func=lease_label, disabled=disabled)
        source(a, 'lease_months')
        # The agent searches one district at a time.
        chosen = b.selectbox(t('District', '地区'), districts, index=districts.index(district), disabled=disabled,
                             format_func=lambda code: f'{code} · {district_names[code]}' if code else any_label)
        source(b, 'districts')
        prop = c.selectbox(t('Property type', '房产类型'), properties, index=properties.index(preferences.property_type), disabled=disabled,
                           format_func=lambda v: any_label if v == NO else value_label(v))
        source(c, 'property_type')
        a, b = st.columns(2)
        mrt = a.number_input(t('Furthest walk to an MRT station (m)', '离地铁站最远距离（米）'), min_value=100, step=100, placeholder=any_label, disabled=disabled,
                             value=None if preferences.mrt_distance is None else max(100, preferences.mrt_distance))
        source(a, 'mrt_distance')
        commute = b.number_input(t('Longest commute to your faculty (min)', '到学院的最长通勤时间（分钟）'), min_value=1, placeholder=any_label, disabled=disabled,
                                 value=preferences.commute_minutes)
        source(b, 'commute_minutes')
        labels = {'furnishing': t('Furnishing', '家具'), 'private_bathroom': t('Private bathroom', '独立卫浴'), 'cooking': t('Cooking', '做饭'),
                  'air_conditioning': t('Air conditioning', '空调'), 'pets': t('Pets', '宠物')}
        values = {}
        for column, (field, choices) in zip(st.columns(len(_OPTIONS)), _OPTIONS.items()):
            values[field] = column.selectbox(labels[field], choices, index=choices.index(getattr(preferences, field)), disabled=disabled,
                                             format_func=lambda v: any_label if v == NO else value_label(v))
            source(column, field)
        submitted = st.form_submit_button(submit_label, type='primary', disabled=disabled)
    if submitted:
        after = (
            replace(requirements, max_budget=budget, rental_scope=scope, min_bedrooms=bedrooms, lease_months=lease),
            replace(preferences, districts=[chosen] if chosen else [], mrt_distance=mrt, commute_minutes=commute, property_type=prop, **values),
        )
        st.session_state[f'{key}-revision'] = revision + 1
        on_submit((requirements, preferences), after)


def other_criteria(saved, key, on_drop, disabled=False):
    """The saved criteria the form has no field for, each with a button to drop it: on_drop(item)."""
    shown = in_form(saved['preferences'])
    items = [item for item in saved.get('items') or [] if item['field'] not in shown]
    if not items:
        return
    st.markdown(t('**Other criteria**', '**其他条件**'))
    lang = language()
    for item in items:
        text, drop = st.columns([5, 1], vertical_alignment='center')
        text.write(f"{label(item)}{'：' if lang == 'zh' else ': '}{item['value'][lang]}")
        if note := source_text(item.get('source')):
            text.caption(note)
        if not disabled and drop.button(t('Drop', '去掉'), icon=':material/close:', key=f"{key}-drop-{item['field']}", help=t('Drop this criterion', '去掉这个条件')):
            on_drop(item)


def drop_message(item):
    """The chat message asking the agent to drop one listed criterion."""
    return t(f"Please drop this criterion: {item['label']['en']}.", f"不用再按“{item['label']['zh']}”这个条件找了。")
