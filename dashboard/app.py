"""Entry point (Streamlit Community Cloud runs this file): page navigation.

Locally: NE_DATA_ROOT=data uv run --extra dashboard streamlit run dashboard/app.py
"""

import streamlit as st

st.set_page_config(page_title="New England Demand Forecast", page_icon="⚡", layout="wide")

st.navigation(
    [
        st.Page("forecast_page.py", title="Forecast", icon="⚡", default=True),
        st.Page("operations_page.py", title="Operations", icon="🛠️"),
    ]
).run()
