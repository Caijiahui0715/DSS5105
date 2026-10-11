from dataclasses import replace
from domain.criteria import criteria_message, empty, from_backend


def test_saved_criteria_fill_the_form():
    req, pref = from_backend({'max_price_sgd': 1800, 'rental_scope': 'room', 'district_code': 'D05', 'max_mrt_distance_m': 450.4,
                              'furnishing_types': ['fully_furnished'], 'cooking_level': 'light', 'property_types': ['hdb_flat', 'condominium']})
    assert (req.max_budget, req.rental_scope, req.min_bedrooms) == (1800, 'room', None)
    assert (pref.districts, pref.mrt_distance, pref.furnishing, pref.cooking) == (['D05'], 450, 'fully_furnished', 'light_only')
    # Several property types do not fit the form's single choice.
    assert pref.property_type == 'No preference'
    assert from_backend({}) == empty()


def test_only_changed_fields_are_sent():
    shown = from_backend({'max_price_sgd': 1800, 'rental_scope': 'room'})
    assert criteria_message(shown, shown, 'en') is None
    req, pref = shown
    changed = (replace(req, max_budget=2000.0), replace(pref, districts=['D21'], cooking='allowed'))
    assert criteria_message(shown, changed, 'en') == 'Please update my search criteria: a monthly rent of at most SGD 2,000; in district D21; full cooking allowed.'
    assert criteria_message(shown, changed, 'zh') == '请更新我的找房条件：月租不超过 2,000 新元；在 D21 区；可以正常做饭。'
    cleared = (replace(req, rental_scope=None), pref)
    assert criteria_message(shown, cleared, 'en') == 'Please update my search criteria: either a room or a whole unit.'


def test_sign_up_criteria_become_the_first_message():
    req, pref = empty()
    stated = (replace(req, max_budget=2500.0, rental_scope='entire_unit', min_bedrooms=2), replace(pref, commute_minutes=30, property_type='condominium'))
    assert criteria_message(empty(), stated, 'en', first=True) == (
        "I'm looking for a place to rent: a monthly rent of at most SGD 2,500; a whole unit; at least 2 bedrooms; "
        'at most 30 minutes by public transport to my faculty; property type: condominium.')


def test_the_lease_length_is_a_criterion():
    shown = from_backend({'max_price_sgd': 1800, 'lease_months': 12})
    assert shown[0].lease_months == 12
    req, pref = shown
    assert criteria_message(shown, (replace(req, lease_months=6), pref), 'en') == 'Please update my search criteria: a 6-month lease.'
    assert criteria_message(shown, (replace(req, lease_months=None), pref), 'zh') == '请更新我的找房条件：租期不限。'
