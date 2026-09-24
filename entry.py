import streamlit as st

home_page   = st.Page("main_app.py", title="CAIRN model", icon="🌍")
cached_page = st.Page("pages/1_Cached_Results.py", title="Saved results", icon="📦")

pg = st.navigation([home_page, cached_page])
pg.run()