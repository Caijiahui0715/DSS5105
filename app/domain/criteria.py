"""The criteria forms (sign-up, a conversation's criteria on Home, the long-term profile on the
Profile page) against the agent's saved criteria.

In a conversation the agent keeps the criteria and the forms only suggest changes: what a form
changed is sent to the agent as an ordinary message in the interface language, so the agent applies
it like anything typed in the chat and the change shows in the conversation. The long-term profile is
changed directly, with the agent's own criteria (to_backend).
"""
from content.labels import VALUE_ZH
from domain.models import RentalPreferences, RentalRequirements

NO = 'No preference'
# A conversation's or the long-term profile's saved criteria as the backend sends them, when there are none.
EMPTY = {'preferences': {}, 'sources': {}, 'items': [], 'profile_changes': []}
REQUIREMENT_FIELDS = ('max_budget', 'rental_scope', 'min_bedrooms', 'lease_months')
PREFERENCE_FIELDS = (
    'districts', 'mrt_distance', 'commute_minutes', 'furnishing', 'private_bathroom', 'cooking', 'air_conditioning', 'pets', 'property_type',
)
# Choices the forms offer for the agent's cooking levels.
_COOKING = {'full': 'allowed', 'light': 'light_only', 'none': 'not_allowed'}
_FURNISHING = ('fully_furnished', 'partially_furnished', 'unfurnished')


def empty():
    """Nothing stated yet: no budget, scope, district or limits."""
    return RentalRequirements(None, None, None), RentalPreferences(districts=[], mrt_distance=None, commute_minutes=None)


def from_backend(saved):
    """The agent's saved criteria (server.py's preferences) as the forms show them.
    Criteria the forms have no field for, such as a room type or MRT minutes, are left out."""
    furnishing = list(saved.get('furnishing_types') or [])
    property_types = list(saved.get('property_types') or [])
    distance = saved.get('max_mrt_distance_m')
    requirements = RentalRequirements(saved.get('max_price_sgd'), saved.get('rental_scope'), saved.get('min_bedrooms'), saved.get('lease_months'))
    preferences = RentalPreferences(
        districts=[saved['district_code']] if saved.get('district_code') else [],
        mrt_distance=None if distance is None else round(distance),
        commute_minutes=saved.get('max_commute_minutes'),
        furnishing=furnishing[0] if len(furnishing) == 1 and furnishing[0] in _FURNISHING else NO,
        private_bathroom='yes' if saved.get('private_bathroom_required') else NO,
        cooking=_COOKING.get(saved.get('cooking_level')) or ('light_only' if saved.get('cooking_required') else NO),
        air_conditioning='yes' if saved.get('air_conditioning_required') else NO,
        pets='allowed' if saved.get('pets_allowed_required') else NO,
        property_type=property_types[0] if len(property_types) == 1 else NO,
    )
    return requirements, preferences


def to_backend(requirements, preferences):
    """The forms' values as the agent's criteria (JSON values, None for any): the inverse of
    from_backend for every criterion the forms have a field for."""
    p = preferences
    return {
        'max_price_sgd': None if requirements.max_budget is None else round(requirements.max_budget),
        'rental_scope': requirements.rental_scope,
        'min_bedrooms': requirements.min_bedrooms,
        'lease_months': requirements.lease_months,
        'district_code': p.districts[0] if p.districts else None,
        'max_mrt_distance_m': p.mrt_distance,
        'max_commute_minutes': p.commute_minutes,
        'furnishing_types': [p.furnishing] if p.furnishing in _FURNISHING else None,
        'private_bathroom_required': True if p.private_bathroom == 'yes' else None,
        'cooking_level': {value: level for level, value in _COOKING.items()}.get(p.cooking),
        'cooking_required': None,
        'air_conditioning_required': True if p.air_conditioning == 'yes' else None,
        'pets_allowed_required': True if p.pets == 'allowed' else None,
        'property_types': [p.property_type] if p.property_type != NO else None,
    }


# The agent's criteria behind each form field.
FORM_FIELDS = {
    'max_budget': ('max_price_sgd',), 'rental_scope': ('rental_scope',), 'min_bedrooms': ('min_bedrooms',),
    'lease_months': ('lease_months',), 'districts': ('district_code',), 'mrt_distance': ('max_mrt_distance_m',),
    'commute_minutes': ('max_commute_minutes',), 'furnishing': ('furnishing_types',),
    'private_bathroom': ('private_bathroom_required',), 'cooking': ('cooking_level', 'cooking_required'),
    'air_conditioning': ('air_conditioning_required',), 'pets': ('pets_allowed_required',), 'property_type': ('property_types',),
}


def form_changes(before, after):
    """The agent's criteria behind the form fields that changed from before to after, each a
    (requirements, preferences) pair: {criterion: new value, None to drop it}."""
    old, new = _values(*before), _values(*after)
    values = to_backend(*after)
    return {criterion: values[criterion] for field in FORM_FIELDS if new[field] != old[field] for criterion in FORM_FIELDS[field]}


def in_form(saved):
    """The saved criteria (the agent's JSON values) the forms show as they are; the rest are listed
    apart. A criterion the forms can only show approximately, such as two property types, is listed too."""
    shown = to_backend(*from_backend(saved))
    return {criterion for criterion, value in saved.items() if criterion in shown and shown[criterion] == value}


def criteria_message(before, after, language, first=False):
    """The message asking the agent for what changed from before to after, each a (requirements,
    preferences) pair; None when nothing changed. first: the criteria given at sign-up."""
    old, new = _values(*before), _values(*after)
    phrases = [_phrase(field, new[field], language) for field in new if new[field] != old[field]]
    if not phrases:
        return None
    if language == 'zh':
        return ('我想找房：' if first else '请更新我的找房条件：') + '；'.join(phrases) + '。'
    return ("I'm looking for a place to rent: " if first else 'Please update my search criteria: ') + '; '.join(phrases) + '.'


def _values(requirements, preferences):
    values = {field: getattr(requirements, field) for field in REQUIREMENT_FIELDS}
    values |= {field: getattr(preferences, field) for field in PREFERENCE_FIELDS}
    values['districts'] = sorted(values['districts'] or [])
    return values


def _phrase(field, value, language):
    en, zh = _PHRASES[field](value)
    return zh if language == 'zh' else en


def _choice(value, phrases):
    return phrases.get(value) or phrases[NO]


def _label(value):
    return value.replace('_', ' '), VALUE_ZH.get(value, value)


_PHRASES = {
    'max_budget': lambda v: ('no budget limit', '预算不限') if v is None else (f'a monthly rent of at most SGD {v:,.0f}', f'月租不超过 {v:,.0f} 新元'),
    'rental_scope': lambda v: _choice(v, {
        'room': ('a room in a shared home', '合租的单间'), 'entire_unit': ('a whole unit', '整租'), NO: ('either a room or a whole unit', '单间或整租都可以'),
    }),
    'min_bedrooms': lambda v: ('any number of bedrooms', '卧室数量不限') if v is None else (f'at least {v} bedroom' + ('s' if v != 1 else ''), f'至少 {v} 间卧室'),
    'lease_months': lambda v: ('any lease length', '租期不限') if v is None else (f'a {v}-month lease', f'租期 {v} 个月'),
    'districts': lambda v: ('any district', '区域不限') if not v else (f'in district {" or ".join(v)}', f'在 {"、".join(v)} 区'),
    'mrt_distance': lambda v: ('no limit on the walk to MRT', '离地铁站的距离不限') if v is None else (f'within {v} m walking of an MRT station', f'步行到地铁站不超过 {v} 米'),
    'commute_minutes': lambda v: ('no commute limit', '通勤时间不限') if v is None else (f'at most {v} minutes by public transport to my faculty', f'坐公共交通到我的学院不超过 {v} 分钟'),
    'furnishing': lambda v: ('no furnishing preference', '家具不限') if v == NO else _label(v),
    'private_bathroom': lambda v: _choice(v, {
        'yes': ('a private bathroom', '要独立卫浴'), 'no': ('no private bathroom needed', '不需要独立卫浴'), NO: ('a private bathroom is optional', '独立卫浴可有可无'),
    }),
    'cooking': lambda v: _choice(v, {
        'allowed': ('full cooking allowed', '可以正常做饭'), 'light_only': ('at least light cooking allowed', '至少可以简单做饭'),
        'not_allowed': ('a home where cooking is not allowed', '不允许做饭的房源'), NO: ('no cooking requirement', '做饭不限'),
    }),
    'air_conditioning': lambda v: _choice(v, {
        'yes': ('air conditioning', '要有空调'), 'no': ('no air conditioning needed', '不需要空调'), NO: ('air conditioning is optional', '空调可有可无'),
    }),
    'pets': lambda v: _choice(v, {
        'allowed': ('pets allowed', '允许养宠物'), 'not_allowed': ('no pets needed', '不需要养宠物'), NO: ('no pet requirement', '宠物不限'),
    }),
    'property_type': lambda v: ('any property type', '房产类型不限') if v == NO else (f'property type: {_label(v)[0]}', f'房产类型：{_label(v)[1]}'),
}
