from urllib.request import Request, urlopen
from urllib.parse import urlparse
from io import BytesIO
from PIL import Image
import streamlit as st

@st.cache_data(ttl=3600, show_spinner=False)
def source_image(url):
    """Optional image read into memory only; failed images use a UI placeholder."""
    if urlparse(url).scheme not in ('http', 'https'):
        return None
    try:
        with urlopen(Request(url, headers={'User-Agent':'NUS-Rental-Demo/0.1'}), timeout=2) as response:
            content = response.read(5_000_001)
        if len(content) > 5_000_000:
            return None
        Image.open(BytesIO(content)).verify()
        return content
    except Exception:
        return None
