import os
import sys
import subprocess
import io
import base64
import tempfile
from datetime import datetime
import time

# ---------------------------------------------------------------------------
# Python packages
# ---------------------------------------------------------------------------
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import shutil

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------
from cairnopen import CairnAPI
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(1, os.path.abspath(os.path.join(current_dir, "../")))

from ModelResults import ModelResults
from model_runners import generate_model_id, find_cached_model, trace_model_params_generic
from support_functions import add_new_country, add_all_transmissions, plot_energy_sankey
from app_state import persistent_value, save_persistent, safe_div, safe_div_series

# ===========================================================================
# CONSTANTS
# ===========================================================================

# All 16 EF 3.0 environmental categories tracked in CAIRN
ALL_IMPACTS = [
    "Climate change#Global Warming Potential 100",
    "Ozone depletion#Ozone Depletion Potential",
    "Acidification#Accumulated Exceedance",
    "Ecotoxicity freshwater#Comparative Toxic Unit for ecosystems",
    "Resource use-Energy carriers#Abiotic Resource Depletion",
    "Eutrophication-Aquatic freshwater#Fraction of nutrients reaching freshwater and compartment",
    "Eutrophication-aquatic marine#Fraction of nutrients reaching marine and compartment",
    "Eutrophication-terrestrial#Accumulated Exceedance",
    "Human toxicity-cancer effects#Comparative Toxic Unit for humans",
    "Human toxicity-noncancer effects#Comparative Toxic Unit for humans",
    "Ionising radiation human health#Human exposure efficiency relative to U",
    "Land use#Soil quality index",
    "Resource use-Minerals and metals#Abiotic Resource Depletion",
    "Particulate matter-Respiratory inorganics#Human health effects associated with exposure to PM",
    "Photochemical ozone formation#Tropospheric ozone concentration increase",
    "Water use#User Deprivation Potential",
]

WEST_EU = ['Spain', 'France', 'Germany', 'Portugal', 'United Kingdom', 'Italy', 'Austria']

# Two countries pre-loaded in every base model JSON — they must not be re-added
BASE_COUNTRIES = ["Spain", "France"]

# Path to the planetary boundaries LCA data workbook (relative to current_dir)
PB_DATA_FILE_REL = "./data/BDD_PB_LCA.xlsx"

# Model type → base JSON mapping

MODEL_BASE_FILES = {'CPLEX': {
    "Step 1 - Energy":                   "./Model_base/Model_base_energy_CPLEX.json",
    "Step 2 - Capacity":             "./Model_base/Model_base_capacity_CPLEX.json",}, 
    'HIGHS': {"Step 1 - Energy":                   "./Model_base/Model_base_energy_HIGHS.json",
    "Step 2 - Capacity":             "./Model_base/Model_base_capacity_HIGHS.json",}
}


# ===========================================================================
# HELPERS
# ===========================================================================

def abs_path(*rel_parts: str) -> str:
    """Return an absolute path relative to *current_dir*."""
    return os.path.join(current_dir, *rel_parts)


def file_status(label: str, path: str, col) -> None:
    """Display a ✅/❌ file-existence indicator inside *col*."""
    with col:
        if os.path.exists(path):
            st.success(f"✅ {label} found")
        else:
            st.error(f"❌ {label} missing")


@st.cache_data(show_spinner=False)
def load_countries_csv(path: str) -> list[str]:
    return pd.read_csv(path)["Country"].tolist()


@st.cache_data(show_spinner=False)
def load_population_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, sep=";")[
        ["CCA3", "Country/Territory", "2022 Population"]
    ].set_index("Country/Territory")


@st.cache_data(show_spinner=False)
def load_average_load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, index_col=0, sep=";")


@st.cache_data(show_spinner=False)
def load_pb_excel(pb_data_file: str, sheet_name: str) -> pd.DataFrame:
    return pd.read_excel(pb_data_file, sheet_name=sheet_name)


def load_pb_data(pb_data_file: str, sheet_name: str, head_column: str) -> pd.DataFrame:
    """
    Load planetary-boundaries data and compute 'system PB' column.

    Returns the full DataFrame with a 'system PB' column added.
    """
    pb_data = pd.read_excel(pb_data_file, sheet_name=sheet_name)

    if head_column in pb_data.columns:
        # Standard allocation: multiply share by 20-year horizon
        pb_data["system PB"] = pb_data[head_column] * 20
    else:
       st.warning('Impossible to load PB data.')

    return pb_data


def set_build_summary(step_key: str, **fields) -> None:
    st.session_state[f"{step_key}_build_summary"] = {
        **fields,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }


def render_build_summary(step_key: str, label: str) -> None:
    """Render the last persisted build summary for *step_key*, if any."""
    data = st.session_state.get(f"{step_key}_build_summary")
    if not data:
        st.caption(f"No {label} model built yet in this panel.")
        return
    with st.container(border=True):
        st.markdown(f"**✅ Last build** · `{data.get('model_id', '—')}` · {data['timestamp']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total countries", data.get("total_countries", "—"))
        c1.metric("Extra countries added", data.get("extra_countries", "—"))
        c2.metric("Environmental impacts", data.get("impacts", "—"))
        c2.metric("PB constraints set", data.get("constraints", "—"))
        pop = data.get("population")
        c3.metric("System population", f"{pop:,}" if pop is not None else "—")
        size = data.get("file_size")
        c3.metric("Model file size", f"{size:,} bytes" if size is not None else "—")
        st.caption(f"Saved to `{data.get('output_path', '—')}`")


def set_run_status(duration, step_key: str, status: str) -> None:
    """Persist a run-step status so it survives reruns triggered elsewhere."""
    st.session_state[f"{step_key}_run_status"] = {
        "status": status,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "duration": duration
    }

# ===========================================================================
# APP CONFIGURATION
# ===========================================================================
st.set_page_config(
    page_title="WISE",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("Western-Europe Interface for Sustainable Electricity")
st.markdown(
    "This app uses the **CAIRN API** to build energy-system models with environmental "
    "constraints derived from the Planetary Boundaries framework.  \n"
    "Configure countries, environmental impacts, and allocation methods below."
)
col1, col2 = st.columns(2)
with col1:
    st.image("./images/CAIRN.png", caption="", width=500)
with col2 :
    st.image("./images/EQUALS.png", caption="", width=500)
# ── Sidebar: Cache Status ─────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ℹ️ About This Tool")
    st.markdown("""
    This application provides an interface to optimize electricity systems :
    
    - **🎯 Minimization of unmet electricity demand**
    - **🌱 Planetary Boundaries-constrained optimization**
    - **⚡ Multi-country energy systems**  
    - **Explore justice and equity through scenarios**

    """)
    
    st.markdown("## 🎯 Quick Start")
    st.markdown("""
    1. Configure your study parameters
    2. Select countries and environmental constraints
    3. Run optimization models
    4. Analyze results
    5. Save results (available in page "Saved results")
    6. Run a new scenario
    """)
    st.markdown("---")
    st.image("./images/CAIRN.png", caption="", width=400)
    st.markdown("---")
    st.image("./images/EQUALS.png", caption="", width=400)
    st.markdown("More information about EQUALS: https://arthurclerjon.github.io/equals/ ")
    st.markdown("---")
    st.markdown("## 📞 Support")
    st.markdown("This app was built at CEA GRENOBLE - LSET. For technical support or questions, please write to justine.duval@cea.fr.")

# ===========================================================================
# STUDY CONFIGURATION
# ===========================================================================

st.subheader("🔧 Study Configuration", divider=True)

col1, col2 = st.columns(2)

with col1:
    study_name = st.text_input(
        "📂 Study Name",
        value=persistent_value("study_name", "openmod2026"),
        key="study_name_widget",
    )
    save_persistent("study_name_widget")

with col2:
    _solver_options = ("HIGHS", "CPLEX")
    solver = pb_source = st.radio(
        "Solver",
        _solver_options,
        index=_solver_options.index(persistent_value("solver", "CPLEX")),
        key="solver",
    )
    save_persistent("solver")
base_model_file_1 = MODEL_BASE_FILES[solver]['Step 1 - Energy']
base_model_file_2 = MODEL_BASE_FILES[solver]['Step 2 - Capacity']

# ---- Planetary boundaries source ----
sheet_name_sosos = "SoSOS"
sheet_name_lca = "LCA"
st.session_state["data_source"] = "Balanza2025"

population_file  = abs_path("./data/world_population.csv")
time_series_file = abs_path( "./data/time_series_normalized_2015.csv")
pb_data_file     = abs_path(PB_DATA_FILE_REL)
trace_file       = abs_path(f"./trace_files/{study_name}.csv")

if not os.path.exists('./trace_files/'):
    os.mkdir('./trace_files')

st.session_state["study_name"] = study_name

# ===========================================================================
# COUNTRY SELECTION
# ===========================================================================

st.subheader("🗺️ Countries Configuration", divider="green")

# Load the full list of available countries from the coordinates CSV
try:
    _coords_file = "./data/countries_codes_and_coordinates.csv"
    available_countries = load_countries_csv(_coords_file)
except FileNotFoundError:
    available_countries = []
    st.warning("⚠️ Could not load `countries_codes_and_coordinates.csv`. Country list will be empty.")

container = st.container()

default_sel = WEST_EU

countries_list = container.multiselect(
    "Select countries for your energy system:",
    WEST_EU,
    default=persistent_value("countries_list_select", default_sel),
    key="countries_list_select",
)

save_persistent("countries_list_select")

if countries_list:
    preview = ", ".join(countries_list[:5])
    suffix  = f" … and {len(countries_list) - 5} more" if len(countries_list) > 5 else ""
    st.success(f"✅ **{len(countries_list)} countries selected**: {preview}{suffix}")

st.markdown("""
<style>
.big-font {
    font-size:100px !important;
    background-color: #8CFFA5
 !important;
}
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="big-font">Now your turn to play with levers!</p>', unsafe_allow_html=True)

# ===========================================================================
# DATA PREVIEW
# ===========================================================================

st.subheader("Data Preview", divider="violet")
selected_impacts = [
        "Climate change#Global Warming Potential 100",
        "Eutrophication-Aquatic freshwater#Fraction of nutrients reaching freshwater and compartment",
    ]
available_impacts: list[str] = []
if os.path.exists(pb_data_file):
    pb_data_techno = load_pb_excel(pb_data_file, sheet_name_lca)[
        ["Correspondence Cairn", "Unit", "Solar PV", "Onshore wind"]
    ].set_index("Correspondence Cairn")

    for imp in selected_impacts:
        if imp not in pb_data_techno.index:
            st.warning(f"⚠️ '{imp}' not found in PB data — skipped.")
        else:
            # st.text(pb_data_techno.loc[imp, 'Onshore wind'].round(0))
            available_impacts.append(imp)
            pb_data_techno.loc[imp, 'Solar PV'] = pb_data_techno.loc[imp, 'Solar PV'].round(0)
            pb_data_techno.loc[imp, 'Onshore wind'] = pb_data_techno.loc[imp, 'Onshore wind'].round(0)
            # st.dataframe(pb_data_techno.loc[available_impacts])
else:
    # PB file missing
    available_impacts = list(selected_impacts)

st.caption(f"Valid impacts: {len(available_impacts)}")

# `pop_system` is used further down (SoSOS share, model building) even if
# nothing below manages to compute it — always give it a safe default first.
pop_system = 0

try:
    world_pop = load_population_csv(population_file)

    col1, col2 = st.columns(2)

    st.write("**Environmental impact (per unit MW):**")

    if available_impacts and os.path.exists(pb_data_file):
        st.dataframe(pb_data_techno.loc[available_impacts])

    if countries_list:
        try:
            pop_system = world_pop.loc[countries_list, "2022 Population"].sum()
            st.metric("Total System Population", f"{pop_system:,}")
        except KeyError as exc:
            st.warning(f"Some countries missing from population data: {exc}")
    else:
        st.info("Select at least one country to compute the system population.")

except Exception as exc:
    st.error(f"Error loading data: {exc}")

# ===========================================================================
# LEVEL OF ENERGY DEMAND
# ===========================================================================

st.subheader("📈 1. Lever 1: Energy Demand", divider="green")
st.markdown("Adjust projected electricity demand relative to the 2015 reference year.")
growth_list = {}

for country in countries_list:
    growth_key = f"growth_{country}"
    growth = st.slider(
        f"Demand growth/reduction {country}",
        min_value=-50, max_value=50,
        value=persistent_value(growth_key, 0), step=10,
        help="Applied as a multiplier on each country's average load.",
        key=growth_key,
    )
    save_persistent(growth_key)
    growth_list[country] = growth


# ===========================================================================
# ENVIRONMENTAL IMPACTS & ALLOCATION
# ===========================================================================

st.subheader("🔥 2. Lever 2: Share of Safe Operating Space", divider="green")

col1, col2 = st.columns(2)
with col1:
    _alloc_options = ["Grandfathering", "EPC+GVA (Equal Per Capita + Gross Value Added)", "DLS (Decent Living Standards)"]
    allocation_method = st.radio(
        "Space of safe operating space (SoSOS) allocation method:",
        _alloc_options,
        index=_alloc_options.index(persistent_value("allocation_method", _alloc_options[0])),
        key="allocation_method",
    )
    save_persistent("allocation_method")

with col2:
    multi_pb = st.slider(
        "Expansion of SoSOS",
        min_value=1, max_value=10,
        value=persistent_value("expansion_sosos", 1), step=1,
        key="expansion_sosos",
    )
    save_persistent("expansion_sosos")


ALLOCATION_COLUMN_MAP = {
    "Grandfathering": "SOS GF",
    "DLS (Decent Living Standards)":            "SOS DLS",
    "EPC+GVA (Equal Per Capita + Gross Value Added)":         "SOS EPC_GVA",

}

if allocation_method in ALLOCATION_COLUMN_MAP:
    head_column_allocation = ALLOCATION_COLUMN_MAP[allocation_method]
else:
    st.warning('An error has occured.')

pop_europe = 447315889
try:
    pb_data = load_pb_excel(pb_data_file, sheet_name_sosos)
    pb_data['system PB'] = safe_div_series(
        pb_data[head_column_allocation] * multi_pb * 20 * pop_system, pop_europe
    )
    st.session_state['PB Data'] = pb_data
except Exception as exc:
    pb_data = pd.DataFrame()
    st.error(f"❌ Could not load Planetary Boundaries data: {exc}")

# Map the UI label to the column name used in the Excel workbook
col1, col2 = st.columns(2)
with col1:
    if allocation_method == 'Grandfathering':
        st.image("./images/grandfathering.png", caption="", width=800)
    elif allocation_method == "EPC+GVA (Equal Per Capita + Gross Value Added)":
        st.image("./images/epcgva.png", caption="", width=800)
    elif allocation_method == "DLS (Decent Living Standards)":
        st.image("./images/dls.png", caption="", width=800)
with col2:
    if not pb_data.empty and allocation_method in (
        'Grandfathering',
        "EPC+GVA (Equal Per Capita + Gross Value Added)",
        "DLS (Decent Living Standards)",
    ):
        carrying_capacity = pb_data['Carrying capacity'].iloc[0]

        sosos_share = np.round(pb_data[head_column_allocation][0]*multi_pb*pop_system/pop_europe/pb_data['Carrying capacity'][0]*100, 2)

        st.metric("SoSOS relative to global carbon budget (%)", np.round(sosos_share, 2))
        if carrying_capacity == 0:
            st.caption("⚠️ 'Carrying capacity' is 0 in the PB data — percentage shown as 0.")

# ===========================================================================
# TRANSMISSION CONSTRAINT
# ===========================================================================

st.subheader("🔄 3. Lever 3: Interconnections", divider="green")
st.markdown(
    "Set a maximum capacity for transmissions to develop (GW)"
)
transmission_constraint = st.slider(
    "Maximum transmission capacity (GW)",
    min_value=0, max_value=300,
    value=persistent_value("transmission_max", 0), step=50,
    key="transmission_max",
)
save_persistent("transmission_max")
st.write("The current constraint is ", transmission_constraint)

# Summary parameter dict
build_params = {
    "countries_list":        countries_list,
    "number_countries":      len(countries_list),
    "environmental_impacts": available_impacts,
    "allocation_method":     allocation_method,
    "data_source":           st.session_state.get("data_source", ""),
    "transmission_constraint": transmission_constraint,
    "expansion_sosos": st.session_state['expansion_sosos'],
}


# ===========================================================================
# MODEL BUILDING & OPTIMISATION 
# ===========================================================================

st.subheader("🧱 Build & Run Models", divider="orange")

def build_and_run_model(base_model_file, step_type, time_series_file, pb_data_file, force = False):
    
    try:
        with st.spinner(f"Building CAIRN model {step_type.capitalize()}…"):

            # ---- Load / create model trace ----
            trace_df = (
                pd.read_csv(trace_file, delimiter=";")
                if os.path.exists(trace_file)
                else pd.DataFrame()
            )

            full_params = {
                **build_params,
                "file_path": abs_path("models", study_name),
                "step" : step_type,
                "growth_rates" : growth_list
            }
            # st.text(full_params)

            model_id = generate_model_id(full_params)
            output_dir = abs_path("./models", study_name)
            os.makedirs(output_dir, exist_ok=True)
 
            existing_model_file = os.path.join(output_dir, f"{model_id}.json")
            model_found = os.path.exists(existing_model_file) and not force
            cached_id = model_id
 
            st.write(f'📌 {step_type.capitalize()} Model identifier:', model_id)
            st.text(model_found)

            # ---- Re-use cached model if available ----
            if model_found:
                st.success(f"♻️ Using cached model: `{cached_id}`")
                existing_model_file = abs_path("models", study_name, f"{cached_id}.json")
            
                if os.path.exists(existing_model_file):
                    cairn_instance =  CairnAPI(True)
                    problem = cairn_instance.read_study(existing_model_file)

                    extra_countries = [c for c in countries_list if c not in BASE_COUNTRIES]
                    base_countries  = [c for c in countries_list if c in BASE_COUNTRIES]
                    ordered_countries = base_countries + extra_countries

                    st.session_state.update({
                        "model_path":     existing_model_file,
                        "cairn_problem":  problem,
                        "timeseries":     time_series_file,
                        "countries_list": ordered_countries,
                        "model_id":       cached_id,
                        "step": step_type
                    })
                    st.success("✅ Cached model loaded successfully!")
                    st.info(f"📋 {len(problem.get_components())} components found.")
                    set_build_summary(
                        f"step{1 if step_type == 'energy' else 2}",
                        model_id=cached_id,
                        output_path=existing_model_file,
                        total_countries=len(countries_list),
                    )
                    if step_type == "energy":
                        st.session_state["energy_id"] = cached_id
                else:
                    st.error("❌ Cached model file not found on disk — please rebuild.")

            else:
                # ---- Build brand-new model ----
                progress = st.progress(0)
                status   = st.empty()

                # Step 1 — Initialise CAIRN
                status.text("🔄 Initialising CAIRN API…")
                progress.progress(10)
                cairn_instance = CairnAPI(True)
                problem = cairn_instance.read_study(base_model_file)

                # Step 2 — Attach time-series profiles
                status.text("🔄 Attaching time-series profiles…")
                progress.progress(20)
                problem.add_timeseries(time_series_file)

                # Step 3 — Set tracked environmental impacts
                status.text("🔄 Configuring environmental impacts…")
                progress.progress(30)
                problem.get_tech_eco_analysis().setting_values = {
                    "ConsideredEnvironmentalImpacts": ",".join(available_impacts)
                }

                # Step 4 — Population & PB budgets
                status.text("🔄 Loading population and PB data…")
                progress.progress(40)
                world_pop = load_population_csv(population_file)
                missing_pop_countries = [c for c in countries_list if c not in world_pop.index]
                if missing_pop_countries:
                    st.error(f"❌ No population data for: {', '.join(missing_pop_countries)}. Aborting build.")
                    return
                pop_system = world_pop.loc[countries_list, "2022 Population"].sum()
                if pop_system <= 0:
                    st.error("❌ Computed system population is 0 — cannot continue (check the selected countries).")
                    return
                st.success(f"✅ System population: {pop_system:,}")

                pop_europe = 447315889
                pb_data = load_pb_excel(pb_data_file, sheet_name_sosos)
                pb_data['system PB'] = safe_div_series(
                    pb_data[head_column_allocation] * multi_pb * 20 * pop_system, pop_europe
                )
                # st.dataframe(pb_data)
                st.session_state['PB Data'] = pb_data

                # Step 5 — Add extra countries (Spain & France already in base model)
                status.text("🔄 Adding countries to model…")
                progress.progress(55)
                extra_countries = [c for c in countries_list if c not in BASE_COUNTRIES]
                base_countries = [c for c in countries_list if c  in BASE_COUNTRIES]
                # Rebuild the full ordered list (base countries first)
                ordered_countries = base_countries + extra_countries
                if len(ordered_countries)>2:
                    for i, country in enumerate(extra_countries):
                        country_idx = i + len(base_countries) + 1  
                    
                        add_new_country(problem, country, country_idx, mode='unmet' if step_type == 'energy' else 'old_capacity', ports = True)
                    
                st.success(f"✅ Added countries.")

                # Step 6 — Transmission topology
                status.text("🔄 Configuring transmission topology…")
                progress.progress(65)
                n = len(ordered_countries)
                ec_elec = problem.get_energy_carrier("Electricity#1")
                if transmission_constraint!=0:
                    add_all_transmissions(problem,len(countries_list),countries_list, problem.get_energy_carrier('Electricity#1'), RTE_trans = False, transmission_costs = 8760*transmission_constraint, neighbours_only=True,
                                    mode = step_type, energy_trans = False)
                else: 
                    problem.remove_bus(problem.get_bus('TransmissionCosts'))
            
                # Step 7 — Assign LCA coefficients and production profiles per country
                status.text("🔄 Assigning LCA coefficients and profiles…")
                progress.progress(75)
                for _, row in pb_data_techno.iterrows():
                    # st.dataframe(row)
                    impact = row.name
                    if pd.isna(impact) or impact not in available_impacts:
                        continue
                    for j, country_name in enumerate(ordered_countries, start=1):
                        try:
                            # Grey-content coefficients for lifecycle impacts
                            problem.get_component(f"WindSource#{j}").setting_values = {
                                f"{impact} EmbodiedCoefficient_A": row["Onshore wind"]/1000
                            }
                            problem.get_component(f"PVSource#{j}").setting_values = {
                                f"{impact} EmbodiedCoefficient_A": row["Solar PV"]/1000
                            }
                            # Link to country-specific normalised generation profiles
                            problem.get_component(f"WindSource#{j}").setting_values = {
                                "UseProfileLoadFlux": f"WindProduction{country_name}"
                            }
                            problem.get_component(f"PVSource#{j}").setting_values = {
                                "UseProfileLoadFlux": f"PVProduction{country_name}"
                            }
                            problem.get_component(f"Demand#{j}").setting_values = {
                                "UseProfileLoadFlux": f"Normalized_Consumption{country_name}"
                            }
                        except Exception as exc:
                            st.warning(f"⚠️ {impact} / {country_name}: {exc}")

                # Step 8 — Apply planetary-boundary constraints
                status.text("🔄 Applying planetary-boundary constraints…")
                progress.progress(85)
                constraints_set = []
                for _, row in pb_data.iterrows():
                    impact = row["Correspondence Cairn"]
                    if pd.isna(impact) or impact not in available_impacts:
                        continue
                    tca = problem.get_tech_eco_analysis()
                    tca.setting_values = {f"{impact} MaxConstraint":      1}
                    # st.text(row["system PB"])
                    tca.setting_values = {f"{impact} MaxConstraintValue": row["system PB"]/1000000}
                    constraints_set.append(impact)
                # st.success(f"✅ Constraints applied: {constraints_set}")

        
                average_load = load_average_load_csv("./data/average_consumption_2015.csv")

                for i, country_name in enumerate(ordered_countries):
                    if country_name not in average_load.index:
                        st.error(
                            f"❌ No average-consumption data for '{country_name}' — aborting build."
                        )
                        return
                    demand_comp = problem.get_component(f"Demand#{i + 1}")
                    rate = growth_list.get(country_name, 0)
                    a = rate / 100 + 1
                    avg_load_val = int(average_load.loc[country_name]["Average Consumption 2015"])
                    demand_comp.set_setting_value("Weight", a * avg_load_val / 1000)
                    demand_comp.get_port("PortT1").setting_values = {"Variable": "Weight"}

                # Set constraint on energy from dispatchable sources (using Step 1 results)
                if step_type == 'capacity' :
                    if 'energy_id' in st.session_state :
                        energy_id = st.session_state['energy_id']
                        results_energy_path = f'./models/{study_name}/{energy_id}_results_PLAN.csv'

                        if os.path.exists(results_energy_path):
                            results_energy = pd.read_csv(results_energy_path, sep=';')
                            objective_rows = results_energy[results_energy['Alias'] == 'Objective']['Value']
                            if objective_rows.empty:
                                st.warning(
                                    "⚠️ No 'Objective' row found in Step 1 results — energy constraint not applied."
                                )
                            else:
                                energy_optimum = 1.1 * objective_rows.iloc[0]
                                print(f"Energy optimum from Step 1: {energy_optimum}")
                                # Apply the constraint to the Capacity model
                                problem.get_bus('ConstraintEnergy').set_setting_value(
                                    'MaxIntegrateConstraintBusValue',
                                    energy_optimum
                                )
                                st.success(f"✅ Energy constraint applied: {energy_optimum}")
                        else:
                            st.warning(f"⚠️ Step 1 results not found at {results_energy_path}. Constraint not applied.")
                    else:
                        st.warning("⚠️ No 'energy_id' in session state. Ensure Step 1 (Energy) runs first.")

                # Step 10 - Reduce number of timsteps for optimization 
                divider = 2
                problem.get_simulation_control().set_setting_value('FutureSize', 8760/divider)
                problem.get_simulation_control().set_setting_value('TimeStep', divider*3600)

                # Step 11 — Save model to disk
                status.text("🔄 Saving model…")
                output_dir = abs_path("./models", study_name)
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, f"{model_id}.json")
                problem.save_study(output_path)


                # ---- Trace the new model ----
                trace_model_params_generic(
                    file_path=output_dir,
                    model_id=model_id,
                    params={**build_params, "step": step_type, "growth_rates": growth_list},
                    trace_file=trace_file,
                )
                # st.success(f"📌 Model traced with ID: `{model_id}`")

                
                st.session_state.update({
                    "model_id":       model_id,
                    "model_path":     output_path,
                    "cairn_problem":  problem,
                    "timeseries":     time_series_file,
                    "countries_list": countries_list,
                    })
                if step_type == "energy":
                    st.session_state["energy_id"] = model_id
     
                progress.progress(100)

                st.success("🎉 CAIRN model built successfully!")

        # ---- Skip solving if results for this exact model_id already exist ----
        results_path = os.path.join(output_dir, f"{model_id}_results_PLAN.csv")
        if os.path.exists(results_path) and not force:
            st.info(
                f"♻️ {step_type.capitalize()}: results already exist for "
                f"`{model_id}` — solve skipped. Tick *Force re-run* to solve again."
            )
            st.session_state['solution_exists'] = True
            set_run_status(None, f"step{1 if step_type == 'energy' else 2}", "Cached")
        else:
            with st.spinner("Running optimization..."):
                start_time = time.time()
                try:
                    # Get the problem from session state
                    cairn_instance = CairnAPI(True)
                    path = st.session_state['model_path']
                    time_series_file = st.session_state['timeseries']
                    problem = cairn_instance.read_study(path)
                    problem.add_timeseries(time_series_file)

                    # Add some debugging info
                    st.info(f"Starting optimization for {step_type.capitalize()} model...")

                    # Run the optimization
                    sol = problem.run()
                
                    if sol:
                        # Store solution in session state for later use
                        st.session_state['cairn_solution'] = sol
                        # Get and display status
                        status = sol.status
                    
                        if status == "Optimal":
                            end_time = time.time()
                            duration = end_time-start_time
                            duration_str = f" · {duration:.2f}s" if duration is not None else ""
                            st.success(f"✅ Optimization completed successfully! Status: {status} - {duration_str} ")
                            st.session_state['solution_exists'] = True  
                            st.session_state['cairn_solution'] = sol
                            st.balloons()

                        else:
                            st.warning(f"⚠️ Optimization completed with status: {status}")
                            st.stop()
                            
                        end_time = time.time()
                        duration = end_time-start_time
                        set_run_status(duration, f"step{1 if step_type == 'energy' else 2}", status)
                    else:
                        st.error("❌ Optimization returned no solution")
                    
                except Exception as e:
                    st.error(f"❌ Error during optimization: {e}")
                    st.exception(e)
                    duration = time.time() - start_time
                    set_run_status(duration, f"step{1 if step_type == 'energy' else 2}", "Error")

    except Exception as exc:
        st.error(f"❌ Error building model: {exc}")
        st.exception(exc)

force_rerun = st.checkbox(
    "Force rebuild & re-run",
    value=persistent_value("force_rerun", False),
    help="Ignore any cached model/results and rebuild + re-solve from scratch.",
    key="force_rerun",
)
save_persistent("force_rerun")

if st.button("Build & Run", type="primary"):
    # --- Clear any previous session artefacts ---
    for key in ("cairn_problem", "cairn_solution", "model_path",
                "timeseries", "available_impacts", "solution_exists"):
        st.session_state.pop(key, None)

    # --- Guard clauses ---
    missing_files = [
        name for path, name in [
            (base_model_file_1,   "Base model energy"),
            (time_series_file,  "Time series"),
            (population_file,   "Population data"),
            (pb_data_file,      "Planetary Boundaries data"),
        ]
        if not os.path.exists(path)
    ]
    if missing_files:
        st.error(f"❌ Missing files: {', '.join(missing_files)}")
        st.stop()
    if not countries_list:
        st.error("❌ Please select at least one country.")
        st.stop()
    if not available_impacts:
        st.error("❌ Please select at least one valid environmental impact.")
        st.stop()

    # --- Build and run both models ---
    build_and_run_model(base_model_file_1, "energy",  time_series_file, pb_data_file)
    build_and_run_model(base_model_file_2, "capacity",  time_series_file, pb_data_file)

# ===========================================================================
# RESULTS VISUALISATION
# ===========================================================================
if st.session_state.get('solution_exists', False):
    st.subheader("📈 Dashboard", divider="green")
    st.subheader("Unmet Demand")

    # Use the country list that was actually used to build the current model,
    # not the live multiselect above — the user may have changed the
    # selection since the last "Build & Run" without rebuilding yet.
    dashboard_countries = st.session_state.get('countries_list', countries_list)

    try:
        model = ModelResults(
            st.session_state['model_id'],
            os.path.join(current_dir, "./models/", st.session_state['study_name']),
            len(dashboard_countries),
        )
        model.set_country_names(dashboard_countries)
        model.get_ts(scenario=False, include_dispatchable=False, include_not_covered=True,
                    expensive_grid=True, instant_satis_V2=False)
        model.get_energy(include_not_covered=True, include_dispatchable=False,
                        include_consumption=True, expensive_grid=True)
        model.get_ts_transmission(indiv_transmission=True)
        model.calc_net_transmission_ts()
        # st.text(model.energies[str(1)]['E_notcovered'])
        # st.text(model.energies[str( 1)]['E_load'])
        # Per-country unmet % (safe against a country with 0 load)
        per_country_unmet = {
            # country: safe_div(
            #     model.energies[str(i + 1)]['E_notcovered'],
            #     model.energies[str(i + 1)]['E_load'],
            # ) * 100
            country: model.energies[str(i + 1)]['E_notcovered']/model.energies[str(i + 1)]['E_load']*100 
            for i, country in enumerate(dashboard_countries)
        }

        per_country_trans = {
            country: safe_div(
                model.energies[str(i + 1)]['E_constrans'],
                model.energies[str(i + 1)]['E_load'],
            ) * 100
            for i, country in enumerate(dashboard_countries)
        }

        # Global unmet % (safe against an empty selection)
        tot_unmet = np.mean(list(per_country_unmet.values())) if per_country_unmet else 0.0
        tot_trans = np.mean(list(per_country_trans.values())) if per_country_trans else 0.0
    except Exception as exc:
        st.error(f"❌ Could not compute the dashboard for the current model: {exc}")
        per_country_unmet, per_country_trans, tot_unmet, tot_trans = {}, {}, 0.0, 0.0

    # Display
    cols = st.columns(len(dashboard_countries) + 1)

    with cols[0]:
        st.metric(
            label="🌍 Total (avg)",
            value=f"{tot_unmet:.1f} %",
        )

    for i, (country, pct) in enumerate(per_country_unmet.items()):
        with cols[i + 1]:
            st.metric(
                label=f"🏳️ {country}",
                value=f"{pct:.1f} %",
            )

    st.subheader("Share of satisfied demand from transmissions")

    # Display
    cols = st.columns(len(dashboard_countries) + 1)
    with cols[0]:
        st.metric(
            label="🌍 Total (avg)",
            value=f"{tot_trans:.1f} %",
        )

    for i, (country, pct) in enumerate(per_country_trans.items()):
        with cols[i + 1]:
            st.metric(
                label=f"🏳️ {country}",
                value=f"{pct:.1f} %",
            )

st.subheader("📊 Optimization results", divider="green")
if st.button("Plot Results"):
    st.session_state["show_results"] = True


@st.fragment
def render_optimization_results() -> None:
    """
    Everything below runs as its own fragment: picking a different country in
    the 'Elec Mix' or 'Time Series' tabs only re-runs *this* function, not
    the whole page. That means the study configuration above (sliders,
    checkboxes...) is never touched by these interactions, and the already
    computed figures for the other tabs stay exactly as they are instead of
    disappearing while everything is recomputed from scratch.
    """
    if not st.session_state.get("solution_exists"):
        st.warning("⚠️ No solution found — run the optimisation first.")
        return

    try:
        pb_data        = st.session_state["PB Data"]
        model_id       = st.session_state["model_id"]
        countries_list = st.session_state["countries_list"]
        output_dir     = abs_path("./models", study_name)
        results_csv    = os.path.join(output_dir, f"{model_id}_results_PLAN.csv")
        results_file   = pd.read_csv(results_csv, sep=";")
    except KeyError as exc:
        st.error(f"❌ Missing information to display results ({exc}). Please re-run the build.")
        return
    except FileNotFoundError as exc:
        st.error(f"❌ Results file not found: {exc}")
        return

    model = ModelResults(model_id, f"./models/{study_name}/", len(countries_list))
    model.set_country_names(countries_list)
    model.get_ts(
        scenario=False, include_dispatchable=False,
        include_not_covered=True, expensive_grid=True, instant_satis_V2=False
    )
    model.get_energy(
        include_not_covered=True, include_dispatchable=False,
        include_consumption=True, expensive_grid=True,
    )
    if transmission_constraint!=0:
        model.get_ts_transmission(indiv_transmission=True)
    model.get_capacities()

    tab_pb, tab_cap, tab_mix, tab_sankey, tab_ts, tab_interconnections, tab_imp_exp = st.tabs(
        ["🌍 PB Impacts", "🏗️ Capacities", "📊 Electricity Mix", "🌊 Sankey", "📈 Time Series" , "🔄 Interconnections", "📊 Imports/Exports"]
    )

    # ---- Relative planetary-boundary impacts ----
    with tab_pb:
        st.subheader("🌍 Relative Planetary Boundary Impacts")
        limit_df = pd.DataFrame(index=available_impacts, columns=["Limits set", "Impact", "Unit"])

        for cat in limit_df.index:
            mask = results_file["Indicator"] == f"Total Project Embodied env impact of {cat}"
            if mask.any():
                limit_df.loc[cat, "Unit"]   = results_file.loc[mask, "Unit"].values[0]
                limit_df.loc[cat, "Impact"] = results_file.loc[mask, "Value"].values[0]
            pb_row = pb_data.loc[pb_data["Correspondence Cairn"] == cat, "system PB"]
            if not pb_row.empty:
                limit_df.loc[cat, "Limits set"] = pb_row.values[0]/1000

        limit_df = limit_df.astype({"Impact": float, "Limits set": float})
        limit_df["relative impact"] = safe_div_series(limit_df["Impact"] * 1000, limit_df["Limits set"])
        if (limit_df["Limits set"] == 0).any() or limit_df["Limits set"].isna().any():
            st.caption("⚠️ Some categories have no Planetary Boundary limit set — their relative impact is shown as 0.")
        st.dataframe(limit_df, use_container_width=True)

        fig_bar = px.bar(
            limit_df.reset_index().rename(columns={"index": "Category"}),
            x="Category", y="relative impact",
            text="relative impact",
            color="relative impact", color_continuous_scale="Viridis",
            title="Relative Impacts vs Planetary Boundaries",
            labels={"relative impact": "Impact / Limit", "Category": "Environmental Category"},
        )
        fig_bar.add_hline(y=1.0, line_dash="dash", line_color="red",
                          annotation_text="Planetary Boundary", annotation_position="top right")
        fig_bar.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig_bar.update_layout(coloraxis_showscale=False, margin=dict(t=80, b=40, l=40, r=40))
        st.plotly_chart(fig_bar, use_container_width=True)

    # ---- Capacities ----
    with tab_cap:
        st.subheader("🏗️ Installed Capacities")
        current_wind_cap = {'Spain':33, 'France':22.9, 'Germany':82, 'Portugal':6.2, 'United Kingdom':33.5, 'Italy':14, 'Austria':4.1}
        current_pv_cap = {'Spain':76, 'France':22.9, 'Germany':128, 'Portugal':7.3, 'United Kingdom':23, 'Italy':47, 'Austria':9.8}
        st.plotly_chart(model.plot_capacities(current_wind_cap=current_wind_cap, current_pv_cap=current_pv_cap), use_container_width=True)

    # ---- Electricity mix ----
    with tab_mix:
        st.subheader("📊 Electricity Mix per Country")
        st.text(model.energies[str(1)]['E_curt'])
        mix_country = st.selectbox(
            "Country", countries_list, key="elec_mix_country_select",
        )
        st.plotly_chart(
            model.plot_elec_mix(countries_list.index(mix_country) + 1),
            use_container_width=True,
            key="elec_mix_selected",
        )
        with st.expander("Show all countries"):
            for i in range(1, len(countries_list) + 1):
                # st.markdown(f"**{countries_list[i - 1]}**")
                st.text(model.energies[str(i)]['E_cons'])
                st.text(model.energies[str(i)]['E_notcovered'])
                st.text(model.energies[str(i)]['E_load'])
                st.plotly_chart(model.plot_elec_mix(i), use_container_width=True, key=f"elec_mix_all_{i}")

    # ---- Energy Sankey ----
    with tab_sankey:
        st.subheader("🌊 Energy Flow (Sankey)")
        try:
            fig_sankey = plot_energy_sankey(
                [model],
                no_countries=list(range(1, len(countries_list) + 1)),
                sources=("Wind", "PV", "Unmet"),
                include_expensive=True,
            )
            st.plotly_chart(fig_sankey, use_container_width=True)
        except Exception as exc:
            st.warning(f"Sankey diagram unavailable: {exc}")

    # ---- Time-series per country ----
    with tab_ts:
        st.subheader("📈 Time Series")
        ts_country = st.selectbox(
            "Country", countries_list, key="time_series_country_select",
        )
        j = countries_list.index(ts_country)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**{model.country_names[j]} — Demand vs Supply**")
            fig_ts = model.plot_demand_supply_ts(
                j + 1, expensive_grid=True,
                include_dispatchable=False, showfig=False,window_size = 1, transmission=(False if transmission_constraint==0 else True), specified_unit = 'GW'
            )
            st.plotly_chart(fig_ts, use_container_width=True, key="ts_demand_supply_selected")
        with col2:
            st.markdown(f"**{model.country_names[j]} — Production Stack**")
            st.plotly_chart(model.stack_time_series(j + 1, showfig=False), use_container_width=True, key="ts_stack_selected")

        with st.expander("Show time series for all countries"):
            for j in range(model.nb_country):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**{model.country_names[j]} — Demand vs Supply**")
                    fig_ts = model.plot_demand_supply_ts(
                        j + 1, expensive_grid=True,
                        include_dispatchable=False, window_size = 1, showfig=False, transmission=(False if transmission_constraint==0 else True),
                    )
                    st.plotly_chart(fig_ts, use_container_width=True, key=f"ts_demand_supply_all_{j}")
                with col2:
                    st.markdown(f"**{model.country_names[j]} — Production Stack**")
                    st.plotly_chart(model.stack_time_series(j + 1, showfig=False), use_container_width=True, key=f"ts_stack_all_{j}")

    # Interconnections map
    with tab_interconnections: 
        st.subheader("🔄 Interconnections")
        # st.text(model.country_names)
        try:
            fig_interco = model.plot_map_transmission(default_unit = 'GWh')
            st.plotly_chart(fig_interco, use_container_width=True)
        except Exception as exc:
            st.warning(f"Interconnections map unavailable: {exc}")

    with tab_imp_exp: 
        st.subheader("📊 Imports/Exports")
        st.text(model.country_names)
        try:
            fig_imp_exp = model.plot_bar_import_export(specified_unit = 'GWh')
            st.plotly_chart(fig_imp_exp, use_container_width=True)
        except Exception as exc:
            st.warning(f"Import/Export chart unavailable: {exc}")
            

    st.success("🎉 All visualisations generated!")

     # ---- Store everything ----
    st.session_state["analysis_results"] = {
        "model_list":     [model],
        "study_name":     study_name,
        "countries_list": countries_list,
        "selected_impacts": selected_impacts,
    }
    st.session_state["last_results"] = {
        "study_name":       study_name,
        "model_id":         model_id,
        "countries_list":   countries_list,
        "selected_impacts": selected_impacts,
        "limit_df":         limit_df,
        "model":            model,
        "build_params":     build_params,
    }


if st.session_state.get("show_results"):
    render_optimization_results()


# =================================
# SAVE CURRENT RESULTS TO CACHE 
# =================================

if "last_results" in st.session_state:
    st.subheader("💾 Save Results", divider="gray")

    default_label = f"{st.session_state['last_results']['study_name']}_{st.session_state['last_results']['model_id']}"
    
    if st.session_state.get("_cache_label_default") != default_label:
        st.session_state["cache_label_input"] = default_label
        st.session_state["_cache_label_default"] = default_label

    cache_label = st.text_input(
        "Label for this run", default_label,
        key="cache_label_input",
    )
 
    if st.button("💾 Save this page's results to cache", key="save_cache_btn"):
        if "results_cache" not in st.session_state:
            st.session_state["results_cache"] = {}

        st.session_state["results_cache"][cache_label] = {
            **st.session_state["last_results"],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        st.success(f"✅ Results saved under: `{cache_label}`")



# ------------------------------------------------ FOOTER -----------------------------------------------------------------
st.markdown("---")
st.markdown("**🔬EQUALS**")
st.markdown("*Built with Streamlit • Powered by CAIRN OPEN • Part of the EQUALS project*")