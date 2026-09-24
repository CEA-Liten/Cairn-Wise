import sys
import os

import streamlit as st
import plotly.express as px

sys.path.insert(1, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app_state import persistent_value, save_persistent, safe_div_series

st.set_page_config(page_title="Cached Results", page_icon="📦", layout="wide")
st.title("📦 Cached Results")

cache = st.session_state.get("results_cache", {})

if not cache:
    st.info("No results saved yet. Go back to the main page and click on 💾.")
    st.stop()

# ===========================================================================
# RUN SELECTION
# =========================================================================
sorted_labels = sorted(cache.keys(), key=lambda l: cache[l].get("timestamp", ""), reverse=True)
_default_selection = [
    l for l in persistent_value("cached_results_selection", [sorted_labels[0]]) if l in cache
] or [sorted_labels[0]]

selected_labels = st.multiselect(
    "Chose runs to visualize and compare :",
    options=list(cache.keys()),
    default=[list(cache.keys())[0]],
     key="cached_results_selection",
  )  # default = most recent
save_persistent("cached_results_selection")
if not selected_labels:
    st.warning("⚠️ Please select at least one run.")
    st.stop()

@st.fragment
def render_run(entry:dict, label: str, container) -> None: 
    with container: 
        st.subheader(f"🔖 {label} — {entry.get('timestamp', '—')}")

        # Older cached entries may miss keys if the app evolved since they
        # were saved — show what we can instead of crashing the whole page.
        required = ["study_name", "countries_list", "selected_impacts", "limit_df", "model"]
        missing = [k for k in required if k not in entry]
        if missing:
            st.error(f"❌ This cached run is missing data ({', '.join(missing)}) and can't be displayed. "
                      "It was probably saved with an older version of the app — consider deleting it.")
            if st.button("🗑️ Delete this run", key=f"delete_broken_{label}"):
                st.session_state["results_cache"].pop(label, None)
                st.rerun(scope="app")
            return

        countries = entry["countries_list"]
        transmission_constraint = entry.get("build_params", {}).get("transmission_constraint", 0)

        c1, c2, c3 = st.columns(3)
        c1.metric("Study", entry["study_name"])
        c2.metric("Countries", len(entry["countries_list"]))
        c3.metric("Impacts", len(entry["selected_impacts"]))

        tab_pb, tab_cap, tab_mix, tab_ts, tab_interconnections = st.tabs(["🌍 PB Impacts", "🏗️ Capacities", "📊 Elec Mix", "📈 Time Series",  "🔄 Interconnections"])

        # ---- Relative planetary-boundary impacts ----
        with tab_pb:
            st.dataframe(entry["limit_df"], use_container_width=True)
            fig_bar = px.bar(
                entry["limit_df"].reset_index().rename(columns={"index": "Category"}),
                x="Category", y="relative impact",
                title="Relative Impacts vs Planetary Boundaries",
            )
            st.plotly_chart(fig_bar, use_container_width=True, key=f"bar_{label}")
        
         # ---- Capacities ----
        with tab_cap:
            try:
                st.plotly_chart(entry["model"].plot_capacities(), use_container_width=True, key=f"cap_{label}")
            except Exception as exc:
                st.warning(f"Capacities plot unavailable: {exc}")

        # ---- Electricity mix ----
        with tab_mix:
            if not countries:
                st.info("No countries in this run.")
            else:
                country = st.selectbox("Country", countries, key=f"mix_country_{label}")
                try:
                    st.plotly_chart(
                        entry["model"].plot_elec_mix(countries.index(country) + 1),
                        use_container_width=True,
                        key=f"mix_selected_{label}",
                    )
                except Exception as exc:
                    st.warning(f"Electricity mix plot unavailable: {exc}")
                with st.expander("Voir tous les pays"):
                    for i in range(1, len(countries) + 1):
                        st.markdown(f"**{countries[i - 1]}**")
                        try:
                            st.plotly_chart(
                                entry["model"].plot_elec_mix(i),
                                use_container_width=True,
                                key=f"mix_all_{label}_{i}",
                            )
                        except Exception as exc:
                            st.warning(f"Electricity mix plot unavailable for {countries[i - 1]}: {exc}")

        # ---- Time Series ----
        with tab_ts:
            if not countries:
                st.info("No countries in this run.")
            else:
                country = st.selectbox("Country", countries, key=f"ts_country_{label}")
                country_idx = countries.index(country) + 1
                try:
                    fig_ts = entry["model"].plot_demand_supply_ts(
                        country_idx, expensive_grid=True,
                        include_dispatchable=False, showfig=False, window_size=1,
                        transmission=(transmission_constraint != 0), specified_unit='GW',
                    )
                    st.plotly_chart(fig_ts, use_container_width=True, key=f"ts_selected_{label}")
                except Exception as exc:
                    st.warning(f"Time series plot unavailable: {exc}")
                with st.expander("Voir tous les pays"):
                    for i in range(1, len(countries) + 1):
                        st.markdown(f"**{countries[i - 1]}**")
                        try:
                            fig_ts_all = entry["model"].plot_demand_supply_ts(
                                i, expensive_grid=True,
                                include_dispatchable=False, showfig=False, window_size=1,
                                transmission=(transmission_constraint != 0), specified_unit='GW',
                            )
                            st.plotly_chart(
                                fig_ts_all,
                                use_container_width=True,
                                key=f"ts_all_{label}_{i}",
                            )
                        except Exception as exc:
                            st.warning(f"Time series plot unavailable for {countries[i - 1]}: {exc}")

        with tab_interconnections: 
            st.subheader("🔄 Interconnections")
            # st.text(model.country_names)
            try:
                fig_interco = entry["model"].plot_map_transmission(default_unit = 'GWh')
                st.plotly_chart(fig_interco, use_container_width=True)
            except Exception as exc:
                st.warning(f"Interconnections map unavailable: {exc}")
 
        if st.button("🗑️ Delete this run", key=f"delete_{label}"):
            st.session_state["results_cache"].pop(label, None)
            st.rerun(scope="app")

if len(selected_labels) ==1:
    render_run(cache[selected_labels[0]], selected_labels[0], st.container())
else:
    cols = st.columns(len(selected_labels), gap="large")
    for label, col in zip(selected_labels, cols):
        render_run(cache[label], label, col)
 
st.divider()
 
if st.button("🗑️ Empty cache."):
    st.session_state["results_cache"] = {}
    st.rerun()