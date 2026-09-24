from __future__ import annotations
from cairnopen import*
import pandas as pd
from pathlib import Path
from functools import lru_cache
import os
import plotly.graph_objects as go
import matplotlib.pyplot as plt
# -----------------------------------------------------------------------------
# PATHS & CONSTANTS
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

COUNTRY_MAP = {
    "Albania": "AL", "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG",
    "Switzerland": "CH", "Czech Republic": "CZ", "Germany": "DE",
    "Denmark": "DK", "Estonia": "EE", "Spain": "ES", "Finland": "FI",
    "France": "FR", "Greece": "GR", "Croatia": "HR", "Hungary": "HU",
    "Ireland": "IE", "Italy": "IT", "Lithuania": "LT", "Luxembourg": "LU",
    "Latvia": "LV", "Montenegro": "ME", "North Macedonia": "MK",
    "Netherlands": "NL", "Norway": "NO", "Poland": "PL",
    "Portugal": "PT", "Romania": "RO", "Serbia": "RS", "Sweden": "SE",
    "Slovenia": "SI", "Slovakia": "SK", "Kosovo": "XK",
}

# -----------------------------------------------------------------------------
# CACHED DATA LOADERS
# -----------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _load_consumption_data() -> pd.DataFrame:
    return pd.read_csv(
        DATA_DIR / "average_consumption_2015.csv",
        sep=";",
        index_col=0,
    )

# -------------------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------------------
def copy_paste_component_param(old_comp, new_comp):
    param_dict = old_comp.setting_values
    # print(param_dict)
    new_comp.setting_values = {k: v for k, v in param_dict.items()}
    return

def _clone_component(problem, ref_name, new_name, model_class=None, profile=None, ports = True):
    """Clone a component and optionally copy all its ports."""
    ref = problem.get_component(ref_name)
    new = Component(problem, new_name, model_class or ref.type)
    # print(problem)
    # Copy all ports from reference
    if ports:
        for ref_port_name in ref.ports:
            ref_port = ref.get_port(ref_port_name)
            carrier = problem.get_energy_carrier(ref_port.carrier_name)
            if ref_port_name not in new.ports:
                Port(new, ref_port_name, carrier) #cette ligne crée effectivement un port. 
            new_port = new.get_port(ref_port_name)
            new_port.set_carrier(carrier)
            new_port.setting_values = ref_port.setting_values
            new_port.set_carrier(carrier)
    
    copy_paste_component_param(ref, new)

    if profile:
        new.set_setting_value('UseProfileLoadFlux', profile)
    return new

def _clone_bus(problem, ref_name, new_name, elec_carrier):
    """Duplicate a reference bus."""
    ref = problem.get_bus(ref_name)
    new = Bus(problem, new_name, "NodeLaw", elec_carrier)
    copy_paste_component_param(ref, new)
    return new

def _clone_manual_constraint(problem, ref_name, new_name, elec_carrier):
    """Duplicate a reference bus."""
    ref = problem.get_bus(ref_name)
    new = Bus(problem, new_name, "ManualConstraint", elec_carrier)
    copy_paste_component_param(ref, new)
    return new


# -----------------------------------------------------------------------------
# SUPPORT FUNCTIONS FOR TRANSMISSIONS
# -----------------------------------------------------------------------------
    
def get_trans_capcity_between_countries(file_path, country_from, country_to):
    """
    Calculates the total maximum power (MW) that can leave a country 
    based on an Excel file containing NTC data.
    """
    
    # 1. Mapping full names to the ISO codes in your table
    country_map = {
        "Albania": "AL", "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG",
        "Switzerland": "CH", "Czech Republic": "CZ", "Germany": "DE", "Denmark": "DK",
        "Estonia": "EE", "Spain": "ES", "Finland": "FI", "France": "FR",
        "Greece": "GR", "Croatia": "HR", "Hungary": "HU", "Ireland": "IE",
        "Italy": "IT", "Lithuania": "LT", "Luxembourg": "LU", "Latvia": "LV",
        "Montenegro": "ME", "North Macedonia": "MK", "Netherlands": "NL", 
        "Norway": "NO", "Poland": "PL", "Portugal": "PT", "Romania": "RO", 
        "Serbia": "RS", "Sweden": "SE", "Slovenia": "SI", "Slovakia": "SK", 
        "Kosovo": "XK"
    }

    # 2. Get the code for the requested country
    target_code = country_map.get(country_to)
    origin_code = country_map.get(country_from)
    if not target_code:
        return f"Error: '{country_to}' is not in the mapping dictionary."
    elif not origin_code: 
         return f"Error: '{country_from}' is not in the mapping dictionary."
    # 3. Load the Excel file
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        return f"Error reading the file: {e}"
    df = df[df['Year']==2024]

    tc=0
    filter1 = df[(df['To'] == target_code) & (df['From'] == origin_code)]
    filter2 = df[(df['From'] == target_code) & (df['To'] == origin_code)]
    if not filter1.empty:
        tc += df[(df['To'] == target_code) & (df['From'] == origin_code) ]['NTC_F'].values[0]
    elif not filter2.empty :
        tc += df[(df['From'] == target_code)&(df['To'] == origin_code)]['NTC_B'].values[0]
    return tc


def add_all_transmissions(problem,n_countries,countries_list, carrier, RTE_trans = False, transmission_costs = None, neighbours_only = False, mode = 'energy', energy_trans = False):
    # Each new country should have a transmission with its neighbours

    # get neghbours from csv file
    neighbours = pd.read_csv(os.path.join(DATA_DIR,'neighboring_countries_europe.csv'), sep = ';', index_col=0)

    if mode == 'minmax' or mode == 'min_trans': 
        problem.create_bus('TransmissionCosts', 'ManualConstraint', carrier)

    for i in range(1, n_countries+1):
        # get neighbouring countries for each country in the problem
        neighbouring_countries = neighbours.loc[countries_list[i-1], "Neighboring Countries"].split(', ')

        if not neighbours_only: 
            neighbouring_countries = [country for country in countries_list if country != countries_list[i-1]]

        # loop over neighbors to add transmission
        for j,nc in enumerate(neighbouring_countries): 
            # check if nc has been added to the problem 
            if nc in countries_list: # it means it has been added
                # create a converter to model the transmission
                problem.create_component(f'Transmission{i}to{countries_list.index(nc)+1}', 'Converter')
                trans = problem.get_component(f'Transmission{i}to{countries_list.index(nc)+1}')
                
                # add port to set a cost for the use of transmission
                for port in trans.ports: 
                    trans.get_port(port).set_carrier(carrier)

                carrier = problem.get_energy_carrier('Electricity#1')
                trans.add_port("PortB0", carrier)
                trans.set_setting_value('MaxPower', -1000)
                # add links 
                problem.add_link(trans.get_port("PortR0"), problem.get_bus(f'NodeLaw#{countries_list.index(nc)+1}'))
                problem.add_link(trans.get_port("PortL0"), problem.get_bus(f'NodeLaw#{i}'))
                trans.set_setting_value('LPModelONLY', True)
                if RTE_trans: 
                    file_path = DATA_DIR /'Existing_transmissions/Interconnectors/REF_NTC.csv'
                    max = get_trans_capcity_between_countries(file_path, countries_list[i-1], nc)
                    # print('this is'+str(max))
                elif transmission_costs: 
                    trans.get_port('PortB0').set_setting_value('Coeff', 1)
                    trans.get_port('PortB0').set_setting_value('Variable', 'MaxPower')
                    # print(trans.setting_values)
                    trans.set_setting_value('EcoInvestModel', False)
                    problem.add_link(trans.get_port("PortB0"), problem.get_bus(f'TransmissionCosts'))
                    problem.get_bus('TransmissionCosts').set_setting_value('MaxIntegrateConstraint', 1)
                    problem.get_bus('TransmissionCosts').set_setting_value('MaxIntegrateConstraintBusValue', transmission_costs)
                    
                    trans.set_setting_value('MaxPower', -1e3)
                    trans.set_setting_value('Efficiency', 0.80)
                    trans.add_port('PortB1',carrier, variable = "PowerOut", direction = 'DATAEXCHANGE')
                    if mode == 'energy' and energy_trans:
                        # link between transmission and manualobjective
                        problem.add_link(trans.get_port('PortB1'),problem.get_bus('ManualObjective#1'))
                        trans.get_port('PortB1').setting_values = {'Coeff': 0.0001, 'Variable': 'PowerOut'}
                    elif mode == 'capacity' and energy_trans:
                        # link between transmission and manualobjective
                        problem.add_link(trans.get_port('PortB1'),problem.get_bus('ConstraintEnergy'))
                        trans.get_port('PortB1').setting_values = {'Coeff': 0.0001, 'Variable': 'PowerOut'}
                    elif mode == 'lexicographic' and energy_trans:
                        problem.add_link(trans.get_port('PortB1'),problem.get_bus('ObjectiveEnergy'))
                        trans.get_port('PortB1').setting_values = {'Coeff': 0.0001, 'Variable': 'PowerOut'}
                    elif mode == 'minmax' :
                        print('No cost added for transmitted energy.')

                    elif mode == 'min_trans':
                        problem.add_link(trans.get_port("PortB1"), problem.get_bus(f'ManualObjective#1'))
                        trans.get_port('PortB1').setting_values = {'Variable': 'PowerOut'}

                elif energy_trans: 
                    problem.add_link(trans.get_port("PortB0"), problem.get_bus(f'ManualObjective#1'))
                    trans.get_port('PortB0').set_setting_value('Coeff', 0.0001)
    return

def add_new_country(problem, country_name, no_country, mode = 'unmet',ports=True):
    """
    Function to add a new country. 
    """
    elec = problem.get_energy_carrier("Electricity#1")

    # ------------------------------------------------------------------
    # COMPONENT COPY SIMPLIFIED
    # ------------------------------------------------------------------
    def C(ref, name, model=None, profile=None):
        return _clone_component(problem, ref, name, model, profile, ports)

    # ------------------------------------------------------------------
    # BASE COMPONENTS
    # ------------------------------------------------------------------
    myPV = C("PVSource#2", f"PVSource#{no_country}", "SourceLoad", f"PVProduction{country_name}")
    myWind = C("WindSource#2", f"WindSource#{no_country}", "SourceLoad", f"WindProduction{country_name}")

    demand_profile = (
         f"Normalized_Consumption{country_name}"
    )
    myDemand = C("Demand#2", f"Demand#{no_country}", "SourceLoad", demand_profile)

    mySto = C("StorageGen#2", f"StorageGen#{no_country}", "StorageGen")
    myCurt = C("Curtailment#2", f"Curtailment#{no_country}", "GridFree")
    myNotCov = C("NotCovered#2", f"NotCovered#{no_country}", "GridFree")

    weight = _load_consumption_data().loc[country_name, "Average Consumption 2015"]/1000
    myDemand.set_setting_value(
        "Weight",
        weight.round(0)
    )

    # ------------------------------------------------------------------
    # MAIN NODE LAW
    # ------------------------------------------------------------------
    bus_ref = "NodeLaw#2" 
    nodelaw = _clone_bus(problem, bus_ref, f"NodeLaw#{no_country}", elec)

    for comp in (myPV, myWind, mySto):
        problem.add_link(comp.get_port("PortL0"), nodelaw)
    problem.add_link(myCurt.get_port("PortR0"), nodelaw)
    problem.add_link(myNotCov.get_port("PortR0"), nodelaw)
    problem.add_link(myDemand.get_port("PortL0"), nodelaw)

    # ------------------------------------------------------------------
    # STORAGE SIZE
    # ------------------------------------------------------------------
    nodelaw_size = _clone_bus(problem, "StorageSize#2", f"StorageSize#{no_country}", elec)
    problem.add_link(mySto.get_port("PortR0"), nodelaw_size)
    problem.add_link(myDemand.get_port("PortT1"), nodelaw_size)

    # ------------------------------------------------------------------
    # OBJECTIVE
    # ------------------------------------------------------------------
    if mode != 'lexicographic':
        multiobj = problem.get_bus(
            "ManualObjective#1" if mode in ("unmet", "nuchydro", "capacity", 'mga2', 'old_capacity') else "MultiObjective#1"
        )
    else: 
        multiobj1 = problem.get_bus("ObjectiveEnergy")
        multiobj2 = problem.get_bus("ObjectiveCapacity")

    if mode == 'old_capacity':
        problem.add_link(myNotCov.get_port("PortT0"), multiobj)
        # problem.add_link(myNotCov.get_port("PortT0"), multiobj)
        myNotCov.get_port("PortT0").set_setting_value('Variable', 'MaxFlow')
        myNotCov.get_port('PortT1').set_setting_value('Variable', 'GridFlow')
        problem.add_link(myNotCov.get_port("PortT1"),  problem.get_bus("ConstraintEnergy"))
        problem.get_bus('ConstraintEnergy').set_setting_value('MaxIntegrateConstraint','true' )
    elif mode == 'unmet': 
        if not "PortT0" in myNotCov.ports: 
            myNotCov.add_port("PortT0", variable = 'GridFlow', carrier = elec)
        problem.add_link(myNotCov.get_port("PortT0"), multiobj)

    elif mode == 'capacity':
        myNotCov.get_port('PortT1').set_setting_value('Variable', 'GridFlow')
        problem.add_link(myNotCov.get_port("PortT1"),  problem.get_bus("ConstraintEnergy"))
        problem.get_bus('ConstraintEnergy').set_setting_value('MaxIntegrateConstraint','true' )
        problem.get_bus('ConstraintEnergy').set_setting_value('MaxIntegrateConstraintBusValue',8574740000 )

        # New way to build this objective 
        myAgregate = _clone_bus(problem, 'AgregateUnmet#2', f'AgregateUnmet#{no_country}', elec)
        myTotUnmet = C('TotUnmet#2', f'TotUnmet#{no_country}', 'GridFree')
        # link Notcovered to agregate
        myNotCov.get_port('PortT0').set_setting_value('Variable', 'GridFlow')
        problem.add_link(myNotCov.get_port("PortT0"),  myAgregate)
        if expensive_grid: 
            # link expensivegrid to agregate
            myGrid.get_port('PortB0').set_setting_value('Variable', 'GridFlow')
            problem.add_link(myGrid.get_port("PortB0"),  myAgregate)
        # link agregate to totunmet
        problem.add_link(myTotUnmet.get_port("PortR0"),  myAgregate)
        # link totunmet to manualobj
        problem.add_link(myTotUnmet.get_port("PortT0"),  multiobj)

    elif mode == 'capacity_max':
        myNotCov.get_port('PortT1').set_setting_value('Variable', 'GridFlow')
        problem.add_link(myNotCov.get_port("PortT1"),  problem.get_bus("ConstraintEnergy"))
        problem.get_bus('ConstraintEnergy').set_setting_value('MaxIntegrateConstraint','true' )
        problem.get_bus('ConstraintEnergy').set_setting_value('MaxIntegrateConstraintBusValue',8574740000 )

        # New way to build this objective 
        myAgregate = _clone_bus(problem, 'AgregateUnmet#2', f'AgregateUnmet#{no_country}', elec)
        myTotUnmet = C('TotUnmet#2', f'TotUnmet#{no_country}', 'GridFree')
        # link Notcovered to agregate
        myNotCov.get_port('PortT0').set_setting_value('Variable', 'GridFlow')
        problem.add_link(myNotCov.get_port("PortT0"),  myAgregate)
        if expensive_grid: 
            # link expensivegrid to agregate
            myGrid.get_port('PortB0').set_setting_value('Variable', 'GridFlow')
            problem.add_link(myGrid.get_port("PortB0"),  myAgregate)
        # link agregate to totunmet
        problem.add_link(myTotUnmet.get_port("PortR0"),  myAgregate)
        # link totunmet to manualobj
        problem.add_link(myTotUnmet.get_port("PortT0"),  multiobj)
        multiobj.set_setting_value('CommoMaxVariable', 1)
    
    elif mode == 'lexicographic':
        myNotCov.get_port("PortT0").set_setting_value('Variable', 'MaxFlow')
        myNotCov.get_port('PortT1').set_setting_value('Variable', 'GridFlow')
        problem.add_link(myNotCov.get_port("PortT0"), multiobj2)
        problem.add_link(myNotCov.get_port("PortT1"), multiobj1)

    # ------------------------------------------------------------------
    # COEFFICIENTS
    # ------------------------------------------------------------------
    if mode in ("standard", "v5"):
        myDemand.get_port("PortB0").set_setting_value("Coeff", "-0.25")
        myDemand.get_port("PortT0").set_setting_value("Coeff", "-0.1")
        mySto.get_port("PortR0").set_setting_value("Coeff", "-0.1")
    else:
        myDemand.get_port("PortT1").set_setting_value("Coeff", "-10")
        mySto.get_port("PortR0").set_setting_value("Coeff", "1")

    myCurt.get_port("PortR0").set_setting_value("Coeff", "-1")

    return problem


def plot_energy_sankey(
    models,
    no_countries,
    sources=('Wind', 'PV', 'Dispatchable'),
    sinks=('Consumption', 'Curtailment'),
    include_expensive=False,
    savefig=False,
    filename="energy_sankey.html"
):
    """
    General Sankey diagram for energy flows.
    """

    colors_dict = {
        'Wind': 'steelblue',
        'PV': 'gold',
        'Dispatchable': 'crimson',
        'Unmet': 'pink',
        'NotCovered': 'pink',
        'Consumption': '#9467bd',
        'Curtailment': 'cyan'
    }

    country_names = models[0].country_names
    mid_nodes = [country_names[c - 1] for c in no_countries]

    all_nodes = list(sources) + mid_nodes + list(sinks)
    node_indices = {name: i for i, name in enumerate(all_nodes)}

    link_sources, link_targets = [], []
    link_values, link_labels, link_colors = [], [], []

    for model in models:
        for c in no_countries:
            country = country_names[c - 1]
            e = model.energies[str(c)]
            country_idx = node_indices[country]

            # --- Source energy mapping ---
            for src in sources:
                if src == 'Wind':
                    val = e['E_wind']
                elif src == 'PV':
                    val = e['E_pv']
                elif src == 'Dispatchable':
                    val = e['E_disp']
                elif src in ('Unmet', 'NotCovered'):
                    val = e['E_notcovered']
                    if include_expensive:
                        val += e.get('E_expensive', 0)
                else:
                    val = 0

                link_sources.append(node_indices[src])
                link_targets.append(country_idx)
                link_values.append(val)
                link_labels.append(f"{src} → {country}")
                link_colors.append(colors_dict.get(src, 'lightgray'))

            # --- Country → Sinks ---
            sink_values = {
                'Consumption': e['E_cons'],
                'Curtailment': e['E_curt']
            }

            for sink in sinks:
                link_sources.append(country_idx)
                link_targets.append(node_indices[sink])
                link_values.append(sink_values[sink])
                link_labels.append(f"{country} → {sink}")
                link_colors.append(colors_dict.get(sink, 'lightgray'))

    fig = go.Figure(go.Sankey(
        node=dict(
            pad=15,
            thickness=20,
            line=dict(color="black", width=0.5),
            label=all_nodes,
            color="lightgray"
        ),
        link=dict(
            source=link_sources,
            target=link_targets,
            value=link_values,
            label=link_labels,
            color=link_colors
        )
    ))

    fig.update_layout(title_text="Energy Flow Sankey Diagram", font_size=12)

    if savefig:
        fig.write_html(filename)

    return fig
