LABELS = {'source': 'Source data', 'derived': 'Derived value', 'mock': 'Demo estimate', 'unavailable': 'Not available'}

def provenance_for(value):
    return 'unavailable' if value is None or value == 'unknown' or value == '' else 'source'

def display(value):
    if value is None or value == '':
        return 'Not provided'
    if value == 'unknown':
        return 'Not specified'
    return str(value).replace('_', ' ').capitalize() if isinstance(value, str) else str(value)
