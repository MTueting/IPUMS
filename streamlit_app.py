"""IPUMS International catalog explorer.

    streamlit run streamlit_app.py
"""

import streamlit as st

st.set_page_config(
    page_title="IPUMS International explorer",
    page_icon=":material/public:",
    layout="wide",
)

if "selected_variables" not in st.session_state:
    st.session_state.selected_variables = []

page = st.navigation(
    [
        st.Page("app_pages/browse.py", title="Browse variables", icon=":material/search:"),
        st.Page("app_pages/coverage.py", title="Coverage", icon=":material/grid_on:"),
        st.Page("app_pages/extract.py", title="Build extract", icon=":material/download:"),
    ],
    position="top",
)

st.title("IPUMS International explorer")
page.run()
