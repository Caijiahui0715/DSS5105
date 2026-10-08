import re

LABELS = {'source': 'Source data', 'derived': 'Derived value', 'mock': 'Demo estimate', 'unavailable': 'Not available'}
LABELS_ZH = {'source': '来源数据', 'derived': '派生值', 'mock': '演示估计', 'unavailable': '无数据'}

def provenance_for(value):
    return 'unavailable' if value is None or value == 'unknown' or value == '' else 'source'

def label(provenance):
    from content.i18n import t
    return t(LABELS[provenance], LABELS_ZH[provenance])

def display(value):
    from content.i18n import t, value_label
    if value is None or value == '':
        return t('Not provided', '未提供')
    if value == 'unknown':
        return t('Not specified', '未注明')
    # Coded values such as 'fully_furnished' in words; names and addresses as written.
    return value_label(value) if isinstance(value, str) and re.fullmatch(r'[a-z0-9_]+', value) else str(value)
