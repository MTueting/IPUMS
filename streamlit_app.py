"""IPUMS International catalog explorer.

    streamlit run streamlit_app.py
"""

import streamlit as st

st.set_page_config(
    page_title="IPUMS International explorer",
    page_icon=":material/public:",
    layout="wide",
)

from app_shared import init_state

init_state()

page = st.navigation(
    [
        st.Page("app_pages/assistant.py", title="Ask Claude", icon=":material/auto_awesome:"),
        st.Page("app_pages/browse.py", title="Browse variables", icon=":material/search:"),
        st.Page("app_pages/coverage.py", title="Coverage", icon=":material/grid_on:"),
        st.Page("app_pages/extract.py", title="Build extract", icon=":material/download:"),
        st.Page("app_pages/settings.py", title="Settings", icon=":material/settings:"),
    ],
    position="top",
)

st.title("IPUMS International explorer")
page.run()
