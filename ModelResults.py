from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from functools import lru_cache
from typing import Dict, List, Optional,Tuple
import matplotlib.pyplot as plt
import plotly.colors as pc
import matplotlib.colors as mcolors
import matplotlib.cm as cm
from matplotlib.lines import Line2D
import numpy as np
import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os 

DEFAULT_COLORS = {
    'Wind': 'steelblue',
    'PV': 'gold',
    'Discharge': 'orangered',
    'SOC': 'darkgreen',
    'Charge': 'purple',
    'Consumption': 'green',
    'Dispatchable': 'crimson',
    'Curtailment': 'cyan',
    'NotCovered':'pink', 
    'ExpensiveGrid':'orange',
    'Load':'darkgrey', 
    'Unmet':'pink',
    'Consumption': '#9467bd',
    "Satisfied" :  '#9467bd',
    'Transmission': 'forestgreen',
    'StorageState':'red'
}

# Colonnes standards à extraire depuis le fichier *_results_Results.csv
COL_TEMPLATES = {
"pv": "PVSource#{i}.OUTPUTFlux1",
"wind": "WindSource#{i}.OUTPUTFlux1",
"load": "Demand#{i}.OUTPUTFlux1",
"curt": "Curtailment#{i}.GridFlow",
"disp": "DispatchableSource#{i}.GridFlow",
"notcov": "NotCovered#{i}.GridFlow",
"existingdisp":"NucHydro#{i}.GridFlow", 
"discharge": "StorageGen#{i}.DischargeFlow",
"charge":"StorageGen#{i}.ChargeFlow",
"expensive_grid": "ExpensiveGrid#{i}.GridFlow",
"consumption" : "ConverterProd#{i}.PowerOut", 
"transmission": "FromTransmission#{i}.PowerOut",
"indivtransmission_from":"Transmission#{j}to{i}.PowerOut",
"indivtransmission_to":"Transmission#{j}to{i}.PowerOut",
"curtailmentb": "Curtailmentb#{i}.GridFlow",
"storage_state":"StorageGen#{i}.Estock"}

# Countries coordinates, projection natural-earth 
COUNTRY_COORDS = {
            "Austria": (14.55, 47.52),
            "Belgium": (4.47, 50.50),
            "Bulgaria": (25.49, 42.73),
            "Croatia": (15.20, 45.10),
            "Cyprus": (33.43, 35.13),
            "Czech Republic": (15.47, 49.82),
            "Denmark": (9.50, 56.00),
            "Estonia": (25.01, 58.60),
            "Finland": (25.75, 61.92),
            "France": (2.21, 46.23),
            "Germany": (10.45, 51.17),
            "Greece": (21.82, 39.07),
            "Hungary": (19.50, 47.16),
            "Ireland": (-8.24, 53.41),
            "Italy": (12.57, 41.87),
            "Latvia": (24.60, 56.88),
            "Lithuania": (23.88, 55.17),
            "Luxembourg": (6.13, 49.82),
            "Malta": (14.38, 35.94),
            "Netherlands": (5.29, 52.13),
            "Poland": (19.15, 51.92),
            "Portugal": (-8.22, 39.40),
            "Romania": (24.97, 45.94),
            "Slovakia": (19.70, 48.67),
            "Slovenia": (14.99, 46.15),
            "Spain": (-3.75, 40.46),
            "Sweden": (18.64, 60.13),
            "United Kingdom": (-1.17, 52.36),
        }


# -----------------------------------------------------------------------------
# Utilitaries
# -----------------------------------------------------------------------------

def _rolling_mean(values: pd.Series | np.ndarray, window: int) -> np.ndarray:
    """Lissage simple sans décalage (convolution) avec gestion des bords.
    Retourne un np.ndarray de même longueur que l'entrée."""
    if window <= 1:
        return np.asarray(values)
    s = pd.Series(values)
    return s.rolling(window=window, min_periods=1, center=False).mean().to_list()

def _safe_series(x: Optional[pd.Series]) -> pd.Series:
    return x if isinstance(x, pd.Series) else pd.Series(dtype="float32")

@dataclass
class ModelResults:
    """Conteneur de résultats PERSEE (robuste et économe en mémoire).
        Paramètres
        ---------
        model_name : str
        Nom logique du modèle (préfixe des fichiers de sortie).
        file_path : str | Path
        Dossier contenant les fichiers de résultats.
        nb_country : int
        Nombre de zones/pays dans le système.
        colors : Dict[str, str]
        Palette de couleurs utilisée par défaut pour les graphiques.
    """
    model_name: str
    file_path: Path | str
    nb_country: int
    colors: Dict[str, str] = field(default_factory=lambda: DEFAULT_COLORS.copy())

    # -- champs calculés --
    country_names: List[str] = field(default_factory=list)

    # results containers
    pv_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    wind_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    load_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    curt_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    disp_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    notcovered_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    cons_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    charge_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    discharge_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    expensive_grid_ts: Dict[str, pd.Series] = field(init=False, default_factory=dict)
    curtb_ts : Dict[str, pd.Series] = field(init=False, default_factory=dict)
    estock_ts : Dict[str, pd.Series] = field(init=False, default_factory=dict)

    # internal full file cache
    _df_cache: Optional[pd.DataFrame] = field(init=False, default=None)

    # various metadata
    impacts_env: Dict[str,float] = field(init=False, default_factory=dict)
    energies: Dict[str, Dict[str, float]] = field(init=False, default_factory=dict)
    weights_demand: Dict[str, float] = field(init=False, default_factory=dict)
    weight_optimisation: bool = field(init=False, default=False)
    load_shedding: bool = field(init=False, default=False)

    def __post_init__(self):
        self.file_path = Path(self.file_path)
        if not self.country_names:
            self.country_names = [f"Country {i}" for i in range(1, self.nb_country + 1)]

    # ------------------------------------------------------------------
    # Helpers file
    # ------------------------------------------------------------------
    def __str__(self) -> str:
        return f"{self.file_path}/{self.model_name}"


    def _plan_path(self) -> Path:
        return self.file_path / f"{self.model_name}_results_PLAN.csv"


    def _results_path(self, scenario: bool) -> Path:
        return self.file_path / (
        f"{self.model_name}_results.csv" if scenario else f"{self.model_name}_results_Results.csv"
        )
    # ================================
    #  New unified CSV reader
    # ================================
    def _get_df(self, path: Path) -> pd.DataFrame:
        """
        Load the entire CSV into RAM once.
        Later calls return the cached dataframe, avoiding re-parsing.
        """

        if self._df_cache is not None:
            return self._df_cache

        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")

        self._df_cache = pd.read_csv(
            path,
            sep=";",
            dtype="float32",
            low_memory=False,  # faster when reading whole file
        )

        return self._df_cache
    # ------------------------------------------------------------------
    # Lecture des résultats 
    # ------------------------------------------------------------------
    @staticmethod
    @lru_cache(maxsize=64)
    def _read_columns_cached(path: str, usecols: Tuple[str, ...]) -> pd.DataFrame:
        """Lit des colonnes spécifiques d'un CSV (séparateur ';') avec mise en cache.
        - Dtypes allégés pour limiter la RAM.
        - low_memory=True pour parser en flux.
        La clé de cache inclut le chemin et les colonnes.
        """
        # print(path)
        
        return pd.read_csv(
        path,
        sep=";",
        usecols=list(usecols),
        dtype="float32",
        low_memory=True,
        )
    
    def _read_plan(self) -> Optional[pd.DataFrame]:
        path = self._plan_path()
        if not path.exists():
            print(f"❌ Fichier PLAN introuvable: {path}")
            return None
        try:
            return pd.read_csv(path, index_col=0, sep=';')
        except Exception as e:
            print(f"⚠️ Erreur lecture PLAN {path}: {e}")
            return None

    def get_indicator(self, component: str, impact_name: str) -> float:
        df = self._read_plan()
        if df is None:
            return 0.0
        try:
            data_compo = df.loc[component]
            m = data_compo["Indicator"].eq(impact_name)
            val = float(data_compo.loc[m, "Value"].iloc[0])
            return val
        except Exception:
            return 0.0
        
    def _read_series(self, file_path: Path, column: str) -> Optional[pd.Series]:
        print(column)
        # print(file_path)
        if not file_path.exists():
            print(f"❌ Fichier introuvable: {file_path}")
            return None
        try:
            df = self._read_columns_cached(str(file_path), (column,))
            if column not in df.columns:
                print(f"⚠️ Colonne absente: {column}")
                return None
            return df[column]
        except Exception as e:
            print(f"⚠️ Erreur lecture {file_path} [{column}]: {e}")
            return None
    @staticmethod
    def curved_arc(lon0, lat0, lon1, lat1, curvature=0.2, n=30):
        import numpy as np

        t = np.linspace(0, 1, n)

        lon_mid = (lon0 + lon1) / 2
        lat_mid = (lat0 + lat1) / 2

        dx = lon1 - lon0
        dy = lat1 - lat0

        lon_ctrl = lon_mid - curvature * dy
        lat_ctrl = lat_mid + curvature * dx

        lon = (1 - t)**2 * lon0 + 2*(1 - t)*t * lon_ctrl + t**2 * lon1
        lat = (1 - t)**2 * lat0 + 2*(1 - t)*t * lat_ctrl + t**2 * lat1

        return lon, lat
    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------
    def set_country_names(self, names: List[str]) -> None:
        if len(names) != self.nb_country:
            raise ValueError("Le nombre de noms ne correspond pas à nb_country.")
        self.country_names = names

    def set_satisfaction(self, t_a: float, t_t: float) -> None:
        self.t_a, self.t_t = t_a, t_t

    # ================================
    #  Time series energy 
    # ================================
    def get_ts(
        self,
        scenario: bool=False,
        include_not_covered: bool=True,
        include_dispatchable: bool=False,
        include_nuc_hydro: bool=False,
        expensive_grid: bool=True,
        instant_satis_V2: bool=False,
    ) -> None:

        csv_path = self._results_path(scenario)

        df = self._get_df(csv_path)   # <== single CSV read

        self.pv_ts.clear()
        self.wind_ts.clear()
        self.load_ts.clear()
        self.curt_ts.clear()
        self.disp_ts.clear()
        self.notcovered_ts.clear()
        self.cons_ts.clear()
        self.charge_ts.clear()
        self.discharge_ts.clear()
        self.expensive_grid_ts.clear()
        self.estock_ts.clear()

        for i in range(1, self.nb_country + 1):

            idx = str(i)

            # required base columns
            self.pv_ts[idx]        = _safe_series(df.get(COL_TEMPLATES["pv"].format(i=i)))
            self.wind_ts[idx]      = _safe_series(df.get(COL_TEMPLATES["wind"].format(i=i)))
            self.load_ts[idx]      = _safe_series(df.get(COL_TEMPLATES["load"].format(i=i)))
            # self.curt_ts[idx]      = _safe_series(df.get(COL_TEMPLATES["curt"].format(i=i))+df.get(COL_TEMPLATES["curtailmentb"].format(i=i)))
            self.curt_ts[idx]      = _safe_series(df.get(COL_TEMPLATES["curt"].format(i=i)))
            self.charge_ts[idx]    = _safe_series(df.get(COL_TEMPLATES["charge"].format(i=i)))
            self.discharge_ts[idx] = _safe_series(df.get(COL_TEMPLATES["discharge"].format(i=i)))
            self.curtb_ts[idx] = _safe_series(df.get(COL_TEMPLATES["curtailmentb"].format(i=i)))
            self.estock_ts[idx] = _safe_series(df.get(COL_TEMPLATES["storage_state"].format(i=i)))
            # consumption logic
            if instant_satis_V2:
                self.cons_ts[idx] = _safe_series(df.get(COL_TEMPLATES["consumption"].format(i=i))-df.get(COL_TEMPLATES["curtailmentb"].format(i=i)))
            else:
                self.cons_ts[idx] = self.load_ts[idx].copy()

            # dispatchable
            if include_dispatchable:
                self.disp_ts[idx] = _safe_series(df.get(COL_TEMPLATES["disp"].format(i=i)))
            elif include_nuc_hydro:
                self.disp_ts[idx] = _safe_series(df.get(COL_TEMPLATES["existingdisp"].format(i=i)))
            else:
                self.disp_ts[idx] = pd.Series(
                    0, index=self.pv_ts[idx].index, dtype="float32"
                )

            # expensive grid
            if expensive_grid:
                self.expensive_grid_ts[idx] = _safe_series(df.get(COL_TEMPLATES["expensive_grid"].format(i=i)))
                # print(f'expensive grid found for {i}')
            else:
                self.expensive_grid_ts[idx] = pd.Series(
                    0, index=self.pv_ts[idx].index, dtype="float32"
                )

            # not covered
            if include_not_covered:
                self.notcovered_ts[idx] = _safe_series(df.get(COL_TEMPLATES["notcov"].format(i=i)))
            else:
                self.notcovered_ts[idx] = pd.Series(
                    0, index=self.pv_ts[idx].index, dtype="float32"
                )
    
    
    def get_ts_transmission(self, indiv_transmission = True):
        '''Get transmission time series. Call only if the model includes transmissions.
        - indiv_transmisison : if True, it means transmission are modeled between neighbouring countries
                                if False, it means a 'copper plate' is modeled.
        - one-to-one-data: if True, transmission time series are retrieved for every couple of neighbouring countries; 
                            if False, all time series are aggregated
        Returns: 
        - define transmission_ts
        - define transmission_1to1 if one_to_one_data is True
        - actualize energies with E_fromtrans'''

        csv_path = self._results_path(False)
        df = self._get_df(csv_path)   # <== single CSV read

        self.transmission_ts = {}
        self.transmission_ts_received = {}
        self.transmission_ts_sent = {}
        self.curt_final_ts = pd.Series(0,self.pv_ts[str(1)].index)
        self.transmission_1to1 = {}
        for i in range(1, self.nb_country + 1):

            idx = str(i)
            self.transmission_ts[idx] = pd.Series(
                0, index=self.pv_ts[idx].index, dtype="float32"
            )
            self.transmission_ts_received[idx] = pd.Series(
                0, index=self.pv_ts[idx].index, dtype="float32"
            )
            self.transmission_ts_sent[idx] = pd.Series(
                0, index=self.pv_ts[idx].index, dtype="float32"
            )
          
            if indiv_transmission:
                
                for j in range(len(self.country_names)):
                    if not _safe_series(df.get(f'Transmission{j+1}to{i}.PowerOut')).empty:
                        col_r = f'Transmission{j+1}to{i}.PowerOut'
                        col_s = f'Transmission{i}to{j+1}.PowerOut'
                        raw_r = df.get(col_r)
                        raw_s = df.get(col_s)
                        # print(f"[DEBUG] {col} → in df: {col in df.columns if hasattr(df, 'columns') else 'n/a'}, raw={raw}")
                        series_r = _safe_series(raw_r)
                        series_s = _safe_series(raw_s)
                        # print(f"[DEBUG] series empty={series.empty}, sum={series.sum()}")
                        self.transmission_ts[idx] += series_r
                        self.transmission_ts_received[idx] += series_r
                        self.transmission_ts_sent[idx] += series_s
                        self.transmission_1to1[f'{j+1}to{i}'] = series_r.copy()

            else: 
                self.transmission_ts[idx] = _safe_series(df.get(COL_TEMPLATES["transmission"].format(i=i)))
                self.curt_final_ts = _safe_series(df.get("CurtailmentFinal.GridFlow"))
            self.energies[idx]['E_fromtrans'] = float(self.transmission_ts_received[idx].sum())
            self.energies[idx]['E_totrans']= float(self.transmission_ts_sent[idx].sum())

        return  

    def calc_net_transmission_ts(self): 
        '''Calculate net transmission per hour, i.e. energy that is indeed consumed in the country that receives it. 
        '''
        self.net_transmission_ts = {}
        self.cons_transmission_ts = {}

        for i in range(1, self.nb_country + 1):

            idx = str(i)
            self.net_transmission_ts[idx] = self.transmission_ts_received[idx] - self.transmission_ts_sent[idx]
            self.cons_transmission_ts[idx] = self.net_transmission_ts[idx].clip(lower = 0)
            self.energies[idx]['E_constrans'] = float(self.cons_transmission_ts[idx].sum())
            self.energies[idx]['E_nettrans'] = float(self.net_transmission_ts[idx].sum())
        return


    def get_transmission_capacity_by_country(self):
        # Get capacity of transmission installed between two countries 
        self.transmission_capacity_1to1 = {}
        if not self.transmission_1to1: 
            self.get_ts_transmission(one_to_one_data = True)
        
        for j in range(len(self.country_names)):
            for i in range(len(self.country_names)): 
                if f'{j+1}to{i+1}' in self.transmission_1to1.keys():
                    if not f'{i+1}/{j+1}' in self.transmission_capacity_1to1.keys():
                        a = self.transmission_1to1[f'{j+1}to{i+1}'].max() if f'{j+1}to{i+1}' in self.transmission_1to1 else 0
                        b = self.transmission_1to1[f'{i+1}to{j+1}'].max() if f'{i+1}to{j+1}' in self.transmission_1to1 else 0
                        # print(i+1, j+1)
                        # print(a,b)
                        self.transmission_capacity_1to1[f'{j+1}/{i+1}'] = max(a,b)

    # ------------------------------------------------------------------
    # Energy data 
    # ------------------------------------------------------------------
    def get_energy(self, include_dispatchable: bool = True, include_not_covered: bool = True, include_consumption: bool = True, expensive_grid:bool=True, V3:bool=True) -> None:
        '''Create dictionary to gather energy data. 
        Arguments: 
        - inlcude_dispatchable: if there is a dispatchable source; 
        - include_not_covered: if a module notcovered exists; 
        - include_consumption: compute difference between load and what is actually consumed (provided by ENRi sources);
        - expensive_grid: if the expensive_grid is present in the model;  
        Returns: 
        - dictionary with {Energy (str) : value (float)}'''
        
        self.energies = {}
        for i in range(1, self.nb_country + 1):
            k = str(i)
            d = {
                "E_pv": float(self.pv_ts[k].sum()),
                "E_wind": float(self.wind_ts[k].sum()),
                "E_curt": float(self.curt_ts[k].sum()),
                "E_load": float(self.load_ts[k].sum())
            }
            if V3: 
                d["E_curtb"] = float(self.curtb_ts[k].sum())
            if include_dispatchable:
                d["E_disp"] = float(self.disp_ts[k].sum())
            if include_consumption:
                d["E_cons"] = float(self.cons_ts[k].sum())
            if include_not_covered:
                d["E_notcovered"] = float(self.notcovered_ts[k].sum())
            if expensive_grid:
                d["E_expensive"] = float(self.expensive_grid_ts[k].sum())
            self.energies[k] = d
    
    def get_capacities(self):
        '''Get wind and PV capacities by country.
        Returns two dictionaries (dict):
        - wind_cap
        - pv_cap'''

        self.wind_cap = []
        self.pv_cap = []

        for i in range(1, self.nb_country + 1):
            wind_cap_c = self.get_indicator(f"WindSource#{i}", "Component Optimal Weight")
            pv_cap_c = self.get_indicator(f"PVSource#{i}", "Component Optimal Weight")
            self.wind_cap.append(wind_cap_c)
            self.pv_cap.append(pv_cap_c)

        return self.wind_cap, self.pv_cap
    
    def get_capacity_tot(self):
        '''Get Wind and PV capacity agregated for the whole system.
        Returns: 
            - wind_cap_tot (float)
            - pv_cap_tot (float)'''
        
        wind_cap_tot = 0
        pv_cap_tot = 0

        for i in range(1, self.nb_country + 1):
            wind_cap_tot+=self.get_indicator(f"WindSource#{i}", "Component Optimal Weight")
            pv_cap_tot+=self.get_indicator(f"PVSource#{i}", "Component Optimal Weight")
        return wind_cap_tot, pv_cap_tot
    
    def set_storage_size(self):
        if self.model_name[-1]=='h':
            l = len(self.model_name)
            if self.model_name[-3]!='_':
                self.storage_size = self.model_name[-3:-1]
            else:
                self.storage_size = self.model_name[-2:-1]
        return
    
    def get_transmission_tot(self):
        tot_trans = 0
        for i, c in enumerate(self.country_names):
            tot_trans += self.transmission_ts[str(i+1)].max()
        self.transmission_tot = tot_trans
        return tot_trans
    
    def get_unmet_capacity_tot(self):
        tot_cap = 0
        cap_countries = {}
        for i, c in enumerate(self.country_names):
            tot_dispatch_ts = self.expensive_grid_ts[str(i+1)] + self.notcovered_ts[str(i+1)]
            cap_countries[c]= tot_dispatch_ts.max()
            tot_cap += tot_dispatch_ts.max()
        return tot_cap, cap_countries 
    
    # ------------------------------------------------------------------
    # Plots
    # ------------------------------------------------------------------
    
    def plot_unmet_capacities(self, default_unit = None):
        '''Get unmet capacities data and plot them.
        - define self.disp_cap as a dictionary: {country: disp_capacity}
        - plot a bar chart with unmet capacity for each country
        '''

        self.disp_cap =  {}

        for i, country in enumerate(self.country_names):
            tot_disp = self.notcovered_ts[str(i+1)]+self.expensive_grid_ts[str(i+1)]
            self.disp_cap[country] = tot_disp.max()
        # Determine the appropriate unit (MW, GW, TW)
        all_vals = self.disp_cap.values()
        
        max_val = max(abs(v) for v in all_vals)
        if not default_unit:     
            if max_val >= 1e6:
                scale = 1e6
                unit = "TW"
            elif max_val >= 1e3:
                scale = 1e3
                unit = "GW"
            else:
                scale = 1
                unit = "MW"
        else: 
            scale = 1
            unit = default_unit

        # Scale values
        disp_cap_scaled = [v / scale for v in self.disp_cap.values()]

        # Create Plotly bar chart
        fig = go.Figure(data=[
            go.Bar(name='Unmet', x=self.country_names, y=disp_cap_scaled),
        ])

        # Update layout
        fig.update_layout(
            barmode='group',
            title='Capacity',
            xaxis_title='Countries',
            yaxis_title=f'Capacities ({unit})',
            legend_title='Source',
            template='plotly_white'
        )

        return fig
     
    def plot_demand_supply_ts(
        self, no_country: int, savefig: str=None, window_size: int = 10, 
        showfig: bool = True, include_dispatchable: bool = False,
        include_nuc_hydro: bool = False, expensive_grid:bool=True,
        transmission:bool=True, indiv_transmission:bool=False, specified_unit = None
    ) -> go.Figure:
        '''Plot demand/supply time series for the chosen country. 
        Returns a plotly figure.'''
        unit = specified_unit if specified_unit else 'MW'

        i = str(no_country)
        x = list(self.pv_ts[i].index)

        # ---- dictionary to track 1st occurrence for legend purposes
        used_legends = {}

        def add_trace_unique(fig, trace, row, col):
            """Adds trace but removes legend duplicates."""
            name = trace.name
            if name in used_legends:
                trace.showlegend = False
            else:
                used_legends[name] = True
            fig.add_trace(trace, row=row, col=col)

        if include_dispatchable:
            fig = make_subplots(
                rows=2, cols=2, start_cell="bottom-left",
                subplot_titles=("vRE", "Curtailment", "Load", "Dispatchable")
            )
            add_trace_unique(
                fig,
                go.Scatter(
                    x=x, y=_rolling_mean(self.disp_ts[i], window_size),
                    mode="lines", name="Dispatchable",
                    marker=dict(color=self.colors["Dispatchable"])
                ),
                row=2, col=2
            )

        elif include_nuc_hydro:
            fig = make_subplots(
                rows=2, cols=2, start_cell="bottom-left",
                subplot_titles=("vRE", "Curtailment", "Load", "Dispatchable")
            )
            add_trace_unique(
                fig,
                go.Scatter(
                    x=x, y=_rolling_mean(self.disp_ts[i], window_size),
                    mode="lines", name="Existing Dispatchable",
                    marker=dict(color=self.colors["Dispatchable"])
                ),
                row=2, col=2
            )
        elif transmission: 
            self.get_ts_transmission(indiv_transmission=True)
            fig = make_subplots(
                rows=2, cols=2, start_cell="bottom-left",
                subplot_titles=("vRE", "Curtailment", "Load", "Unmet")
            )
            print('Transmission is plotted')
            add_trace_unique(
                fig,
                go.Scatter(
                    x=x, y=_rolling_mean(self.transmission_ts[i], window_size),
                    mode="lines", name="FromTransmission",
                    marker=dict(color=self.colors["Transmission"])
                ),
                row=2, col=2
            )
        
        else:
            fig = make_subplots(
                rows=2, cols=2, start_cell="bottom-left",
                subplot_titles=("vRE", "Curtailment", "Load", "Unmet")
            )

        # === LOAD
        add_trace_unique(
            fig,
            go.Scatter(
                x=x, y=_rolling_mean(self.load_ts[i], window_size),
                mode="lines", name="Load",
                marker=dict(color=self.colors["Load"])
            ),
            row=2, col=1
        )

        add_trace_unique(
            fig,
            go.Scatter(
                x=x, y=_rolling_mean(self.load_ts[i], window_size),
                mode="lines", name="Load",
                marker=dict(color=self.colors["Load"])
            ),
            row=2, col=2
        )

        # === PV
        add_trace_unique(
            fig,
            go.Scatter(
                x=x, y=_rolling_mean(self.pv_ts[i], window_size),
                mode="lines", name="PV",
                marker=dict(color=self.colors["PV"])
            ),
            row=1, col=1
        )

        add_trace_unique(
            fig,
            go.Scatter(
                x=x, y=_rolling_mean(self.pv_ts[i], window_size),
                mode="lines", name="PV",
                marker=dict(color=self.colors["PV"])
            ),
            row=1, col=2
        )

        # === WIND
        add_trace_unique(
            fig,
            go.Scatter(
                x=x, y=_rolling_mean(self.wind_ts[i], window_size),
                mode="lines", name="Wind",
                marker=dict(color=self.colors["Wind"])
            ),
            row=1, col=1
        )

        add_trace_unique(
            fig,
            go.Scatter(
                x=x, y=_rolling_mean(self.wind_ts[i], window_size),
                mode="lines", name="Wind",
                marker=dict(color=self.colors["Wind"])
            ),
            row=1, col=2
        )

        # === CURTAILMENT
        add_trace_unique(
            fig,
            go.Scatter(
                x=x, y=_rolling_mean(self.curt_ts[i], window_size),
                mode="lines", name="Curtailment",
                marker=dict(color=self.colors["Curtailment"])
            ),
            row=1, col=2
        )

        # === UNMET + consumption
        if self.notcovered_ts:
            # add_trace_unique(
            #     fig,
            #     go.Scatter(
            #         x=x, y=_rolling_mean(self.cons_ts[i], window_size),
            #         mode="lines", name="Consumed",
            #         marker=dict(color=self.colors["Consumption"])
            #     ),
            #     row=2, col=1
            # )
            add_trace_unique(
                fig,
                go.Scatter(
                    x=x, y=self.notcovered_ts[i],
                    mode="lines", name="Unmet",
                    marker=dict(color=self.colors["Unmet"])
                ),
                row=2, col=1
            )

        # === storage
        add_trace_unique(
                fig,
                go.Scatter(
                    x=x, y=self.estock_ts[i],
                    mode="lines", name="E_stock",
                    marker=dict(color=self.colors["StorageState"])
                ),
                row=1, col=1
            )

        # === expensive grid
        if expensive_grid:
            add_trace_unique(
                fig,
                go.Scatter(
                    x=x, y=(self.expensive_grid_ts[i]),
                    mode="lines", name="Expensive Grid",
                    marker=dict(color=self.colors["ExpensiveGrid"])
                ),
                row=2, col=2
            )
            add_trace_unique(
                fig,
                go.Scatter(
                    x=x, y=_rolling_mean(self.expensive_grid_ts[i], window_size),
                    mode="lines", name="Expensive Grid",
                    marker=dict(color=self.colors["ExpensiveGrid"])
                ),
                row=1, col=1
            )

        # === axis titles
        for r in (1,2):
            for c in (1,2):
                fig.update_xaxes(title="Time (hour)", row=r, col=c)
                fig.update_yaxes(title=f"Power ({unit})", row=r, col=c)

        fig.update_layout(
            title=f"Optimization results - {self.country_names[no_country-1]} #{no_country}",
            legend_title_text="Components"
        )

        if showfig:
            fig.show()
        if savefig:
            fig.write_html(savefig)

        return fig


    def stack_time_series(self,no_country: int, window_size: int = 24, savefig: bool = False, showfig: bool = True, include_dispatchable: bool = True,
        expensive_grid: bool = False, transmission : bool = False, merge_notcovered: bool=False, default_unit: str = "MW") -> go.Figure:
        
        """Stacked vRE + load + storage.
        Returns a stacked plot of time series of supply and demand for a given country. """
        name = self.country_names[no_country - 1]
        k = str(no_country)
        n = len(self.pv_ts[k])
        x = list(range(n))

        pv = _rolling_mean(self.pv_ts[k], window_size)
        wind = _rolling_mean(self.wind_ts[k], window_size)
        cons = _rolling_mean(self.cons_ts[k], window_size)
        load = _rolling_mean(self.load_ts[k], window_size)
        curt = _rolling_mean(-1*self.curt_ts[k], window_size)  # négatif pour séparation visuelle
        notcov = _rolling_mean(self.notcovered_ts[k], window_size)
        expgrid = _rolling_mean(self.expensive_grid_ts[k], window_size)
        if transmission : 
            trans = _rolling_mean(self.transmission_ts[k], window_size)

        fig = make_subplots(rows=1, cols=1)
    
        if expensive_grid:
            if merge_notcovered: 
                expgrid = notcov + expgrid
                fig.add_trace(go.Scatter(x=x, y=expgrid, mode="lines", name="Expensive Grid", marker=dict(color=self.colors["ExpensiveGrid"]), stackgroup="one"))
            else: 
                fig.add_trace(go.Scatter(x=x, y=expgrid, mode="lines", name="Expensive Grid", marker=dict(color=self.colors["ExpensiveGrid"]), stackgroup="one"))
        
        fig.add_trace(go.Scatter(x=x, y=pv, mode="lines", name="PV", marker=dict(color=self.colors["PV"]), stackgroup="one"))
        fig.add_trace(go.Scatter(x=x, y=wind, mode="lines", name="Wind", marker=dict(color=self.colors["Wind"]), stackgroup="one"))
        # fig.add_trace(go.Scatter(x=x, y=cons, mode="lines", name="Consumption", line=dict(color=self.colors["Consumption"], width=3)))
        fig.add_trace(go.Scatter(x=x, y=load, mode="lines", name="Load (original)", line=dict(color=self.colors["Load"], width=2)))
        fig.add_trace(go.Scatter(x=x, y=curt, mode="lines", name="Curtailment", line=dict(color=self.colors["Curtailment"], width=2)))
        if merge_notcovered:
            fig.add_trace(go.Scatter(x=x, y=expgrid, mode="lines", name="Unmet", line=dict(color=self.colors["Unmet"], width=2)))
        else: 
            fig.add_trace(go.Scatter(x=x, y=notcov, mode="lines", name="Unmet", line=dict(color=self.colors["Unmet"], width=2)))
            fig.add_trace(go.Scatter(x=x, y=expgrid, mode="lines", name="ExpensiveGrid", line=dict(color=self.colors["ExpensiveGrid"], width=2)))
        if transmission: 
            fig.add_trace(go.Scatter(x=x, y=trans, mode="lines", name="Transmission", line=dict(color=self.colors["Transmission"], width=2)))
        
        fig.update_layout(title=f"Optimization results {name} - {self.model_name}", xaxis_title="Time (hour)", yaxis_title=f"Power ({default_unit})")
        if savefig:
            out = Path("figures")
            out.mkdir(parents=True, exist_ok=True)
            fig.write_html(out / f"{name}_stack_ts_positive.html")
        if showfig:
            fig.show()
        return fig
    
    def plot_elec_mix(self, no_country: int) -> go.Figure:
        """Plot electricity mix for a given country index.
        Returns a pie chart with supply shares and curtailed/consumed shares. """
        key = str(no_country)
        if key not in self.energies:
            # Try fallback for 0-based indexing
            key = str(no_country - 1)
        if key not in self.energies:
            raise KeyError(f"Country index {no_country} not found in energies. Available keys: {list(self.energies.keys())}")
        self.get_ts_transmission(indiv_transmission=True)
        self.calc_net_transmission_ts()
        data = self.energies[key]
        labels = ["Wind", "PV", "Satisfied", "Unmet"]
        # labels = [""]
        colors = [DEFAULT_COLORS[label] for label in labels]
        
        pv = float(data.get("E_pv", 0.0))
        wind = float(data.get("E_wind", 0.0))
        transmission = float(data.get('E_constrans', 0.0))
        notcovered = float(data.get('E_notcovered', 0.0))
        curt = float(data.get("E_curt", 0.0))
        cons = float(data.get("E_cons", 0.0))-notcovered
        
        produced = [wind, pv]
        used = [cons, notcovered]

        fig = make_subplots(rows=1, cols=3, specs=[[{"type": "domain"},{"type": "domain"}, {"type": "xy"}]])
        fig.add_trace(go.Pie(
            labels=labels[:2], values=produced,
            marker=dict(colors=colors),
            textinfo="percent+label",
            name="Produced",
            ) ,row = 1, col = 1)

        fig.add_trace(go.Pie(
            labels=labels[2:], values=used,
            marker=dict(colors=colors[2:]),
            textinfo="percent+label",
            name="Used",
            ), row = 1, col = 2)
        print(f"[DEBUG] wind={wind}, pv={pv}, cons={cons}, transmission={transmission}, curt={curt}, notcovered={notcovered}")
        # --- Stacked bar ---
        # On répartit le curtailement proportionnellement entre PV et Wind
        total_produced = wind + pv
        if total_produced > 0:
            curt_wind = curt * (wind / total_produced)
            curt_pv = curt * (pv / total_produced)
        else:
            curt_wind = curt_pv = 0.0

        wind_net = wind - curt_wind
        pv_net = pv - curt_pv
        net_produced = total_produced - curt

        x_cat = ["Produced", "Satisfied"]

        fig.add_trace(go.Bar(
            x=x_cat, y=[total_produced/1000, cons/1000],
            name="Energy",
            marker=dict(color=[DEFAULT_COLORS.get("ExpensiveGrid", "grey"),
                DEFAULT_COLORS.get("Consumption", "grey")]),
            ), row=1, col=3)

        # Barre hachurée
        fig.add_trace(go.Bar(
            x=['Produced'], y=[curt/1000],
            name="Curtailed",
            marker=dict(
                color="grey",
                pattern_shape="/",
                pattern_fgcolor="red",
                pattern_size=6,
            ),
            ), row=1, col=3)

        fig.add_trace(go.Bar(
            x=['Satisfied'], y=[transmission/1000],
            name="Transmission",
            marker=dict(
                color="grey",
                pattern_shape="/",
                pattern_fgcolor="black",
                pattern_size=6,
            ),
            ), row=1, col=3)

        fig.update_layout(
            barmode="overlay",
            title_text=f"Electricity Mix - {self.country_names[no_country-1]}",
            annotations=[dict(text="Usage", x=0.5, y=0.5, font_size=14, showarrow=False)],
            height=400, width=700,
        )

        fig.update_yaxes(title_text="Energy (TWh)", row=1, col=3)

        return fig


    def plot_global_mix(self) -> go.Figure:
        '''Returns a global pie chart for the whole system.
        '''
        labels = ["Wind", "PV", "Dispatchable"]
        colors = [self.colors['Wind'],self.colors['PV'], self.colors['Dispatchable']]

        pv = wind = disp = curt = cons = 0.0
        for i in range(1, self.nb_country + 1):
            k = str(i)
            pv += float(self.energies[k].get("E_pv", 0.0))
            wind += float(self.energies[k].get("E_wind", 0.0))
            disp += float(self.energies[k].get("E_disp", 0.0))
            curt += float(self.energies[k].get("E_curt", 0.0))
            cons += float(self.energies[k].get("E_cons", 0.0))

        produced = [wind, pv, disp]
        used = [cons, curt]

        fig = make_subplots(rows=1, cols=1, specs=[[{"type": "domain"}]])
        fig.add_trace(go.Pie(labels=labels, values=produced, marker=dict(colors=colors), hole=0.3, textinfo="percent+label", name="Produced"))
        fig.add_trace(go.Pie(labels=["Consumed", "Curtailed"], values=used, marker=dict(colors=[self.colors['Consumption'], self.colors["Curtailment"]]), hole=0.7, textinfo="percent+label", name="Usage"))
        fig.update_layout(title_text="Global Electricity Mix", annotations=[dict(text="Usage", x=0.5, y=0.5, font_size=14, showarrow=False)], height=400, width=500)
        fig.show()
        return fig

    def plot_capacities(self, savefig=None, default_unit='GW', output_path=None, dpi=300,
                     current_wind_cap=None, current_pv_cap=None,
                     bargap=0.15, bargroupgap=0.1, line_color_wind='darkblue',
                     line_color_pv='darkorange', line_width=3):

        if not self.wind_cap:
            wind_cap, pv_cap = self.get_capacities()
        else:
            wind_cap, pv_cap = self.wind_cap, self.pv_cap

        all_vals = wind_cap + pv_cap
        max_val = max(abs(v) for v in all_vals)
        if not default_unit:
            if max_val >= 1e6:
                scale = 1e6
                unit = "TW"
            elif max_val >= 1e3:
                scale = 1e3
                unit = "GW"
            else:
                scale = 1
                unit = "MW"
        else:
            scale = 1
            unit = default_unit

        wind_cap_scaled = [v / scale for v in wind_cap]
        pv_cap_scaled = [v / scale for v in pv_cap]

        fig = go.Figure(data=[
            go.Bar(name='Wind', x=self.country_names, y=wind_cap_scaled),
            go.Bar(name='PV', x=self.country_names, y=pv_cap_scaled)
        ])

        fig.update_layout(
            barmode='group',
            bargap=bargap,
            bargroupgap=bargroupgap,
            xaxis_title='Countries',
            yaxis_title=f'Capacities ({unit})',
            legend_title='Source',
            template='plotly_white'
        )

        fig.update_layout(
            annotations=[
                dict(
                    text=f"Solar and Wind Capacities<br><sup>Model: {self.model_name}</sup>",
                    xref="paper", yref="paper",
                    x=0.5, y=1.05,
                    xanchor="center", yanchor="bottom",
                    showarrow=False,
                    font=dict(size=16)
                )
            ],
            height=550,
            margin=dict(l=0, r=0, t=80, b=0),
        )

        # --- Overlay current capacities as horizontal lines on top of each bar ---
        if current_wind_cap is not None or current_pv_cap is not None:
            n_traces = 2  # Wind, PV
            slot_width = (1 - bargap) / n_traces
            bar_width = slot_width * (1 - bargroupgap)
            group_left = -0.5 * (1 - bargap)

            def bar_x_range(trace_index, category_index):
                slot_left = group_left + trace_index * slot_width
                bar_left = slot_left + slot_width * bargroupgap / 2
                x0 = category_index + bar_left
                x1 = x0 + bar_width
                return x0, x1

            def as_dict(data):
                if data is None:
                    return {}
                if isinstance(data, dict):
                    return data
                return dict(zip(self.country_names, data))

            current_wind = as_dict(current_wind_cap)
            current_pv = as_dict(current_pv_cap)

            for i, country in enumerate(self.country_names):
                if country in current_wind:
                    x0, x1 = bar_x_range(0, i)
                    fig.add_shape(
                        type="line", xref="x", yref="y",
                        x0=x0, x1=x1,
                        y0=current_wind[country] / scale, y1=current_wind[country] / scale,
                        line=dict(color=line_color_wind, width=line_width, dash="solid"),
                    )
                if country in current_pv:
                    x0, x1 = bar_x_range(1, i)
                    fig.add_shape(
                        type="line", xref="x", yref="y",
                        x0=x0, x1=x1,
                        y0=current_pv[country] / scale, y1=current_pv[country] / scale,
                        line=dict(color=line_color_pv, width=line_width, dash="solid"),
                    )

            # Dummy traces so the lines show up in the legend
            if current_wind:
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode='lines',
                    line=dict(color=line_color_wind, width=line_width),
                    name='Current Wind Capacity'
                ))
            if current_pv:
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode='lines',
                    line=dict(color=line_color_pv, width=line_width),
                    name='Current PV Capacity'
                ))

        if output_path and savefig:
            fig.write_image(os.path.join(output_path, savefig), scale=dpi / 96)
            print(f"Figure saved to: {os.path.join(output_path, savefig)}")

        return fig

    def plot_sankey_transmission(self):
        '''Plot sent/received energy as a sankey plit between countries.'''

        csv_path = self._results_path(False)
        df = self._get_df(csv_path)   # <== single CSV read

        sources = []
        targets = []
        values = []
        nb_countries = self.nb_country

        for i in range(1, nb_countries + 1):      # TO country
            for j in range(1, nb_countries + 1):  # FROM country
                if i == j:
                    continue

                col = f"Transmission{j}to{i}.PowerOut"
                series = _safe_series(df.get(col))

                if not series.empty:
                    total_energy = series.sum()

                    if total_energy > 0:
                        sources.append(j - 1)  # sankey is 0-indexed
                        targets.append(i - 1)
                        values.append(total_energy)

        # Sankey diagram
        fig = go.Figure(
            go.Sankey(
                node=dict(
                    pad=15,
                    thickness=20,
                    line=dict(color="black", width=0.5),
                    label=self.country_names,
                ),
                link=dict(source=sources,target=targets,value=values)
            )
        )

        fig.update_layout( title_text="Energy Transmission Between Countries", font_size=12)
        fig.show()

        return
    
    
    def plot_map_transmission(self, default_unit = None, output_path = None, savefig = None, dpi = 300):
        '''Plot EU map with transmitted energy between countries. '''
        csv_path = self._results_path(False)
        df = self._get_df(csv_path)

        flows = []

        # --- collect flows ---
        for i in range(1, self.nb_country + 1):
            for j in range(1, self.nb_country + 1):
                if i == j:
                    continue
                col = f"Transmission{j}to{i}.PowerOut"
                series = _safe_series(df.get(col))
                if not series.empty:
                    total = series.sum()
                    if total > 0:
                        flows.append((j, i, total))

        # --- sort descending and keep top N ---
        TOP_N = 20
        flows.sort(key=lambda x: x[2], reverse=True)
        flows_to_draw = flows[:TOP_N]
        max_flow = flows_to_draw[0][2] if flows_to_draw else 1.0

        # --- build labels for bar chart ---
        labels = [
            f"{self.country_names[j-1]} → {self.country_names[i-1]}"
            for j, i, _ in flows_to_draw
        ]
        values = [val for _, _, val in flows_to_draw]

        # ── figure with two subplots ──────────────────────────────────────────────

        from plotly.subplots import make_subplots
        if default_unit: 
            unit = default_unit
        else: 
            unit = "MWh"
        fig = make_subplots(
            rows=1, cols=2,
            column_widths=[0.6, 0.4],
            specs=[[{"type": "geo"}, {"type": "xy"}]],
            subplot_titles=(
                f"Top {TOP_N} transmission flows",
                f"Top {TOP_N} flows ({unit})",
            ),
        )

        # --- draw arcs on map ---
        for j, i, val in flows_to_draw:
            c_from = self.country_names[j - 1]
            c_to   = self.country_names[i - 1]
            print(j,i)
            print(c_from, c_to)
            lon0, lat0 = COUNTRY_COORDS[c_from]
            lon1, lat1 = COUNTRY_COORDS[c_to]

            lon, lat = self.curved_arc(lon0, lat0, lon1, lat1, curvature=0.15)

            fig.add_trace(
                go.Scattergeo(
                    lon=lon,
                    lat=lat,
                    mode="lines",
                    line=dict(width=1 + 6 * val / max_flow, color="crimson"),
                    opacity=0.6,
                    hoverinfo="text",
                    text=f"{c_from} → {c_to}<br>{val:.2f} {unit}",
                    showlegend=False,
                ),
                row=1, col=1,
            )

        # --- country markers ---
        fig.add_trace(
            go.Scattergeo(
                lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
                lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
                mode="markers+text",
                marker=dict(size=6, color="black"),
                text=self.country_names,
                textposition="top center",
                showlegend=False,
            ),
            row=1, col=1,
        )

        # --- bar chart (largest at top → reversed y-axis) ---
        fig.add_trace(
            go.Bar(
                x=values[::-1],
                y=labels[::-1],
                orientation="h",
                marker=dict(
                    color=values[::-1],
                    colorscale="Reds",
                    showscale=False,
                ),
                hovertemplate="%{y}<br>%{x:.2f} {unit}<extra></extra>",
                showlegend=False,
            ),
            row=1, col=2,
        )

        # --- layout ---
        fig.update_layout(
            annotations=[
                dict(
                    text=f"Tansmissions Flows<br><sup>Model: {self.model_name}</sup>",
                    xref="paper", yref="paper",
                    x=0.5, y=1.05,
                    xanchor="center", yanchor="bottom",
                    showarrow=False,
                    font=dict(size=16)
                )
            ],
            height=650,
            geo=dict(
                scope="europe",
                projection_type="natural earth",
                showland=True,
                landcolor="rgb(240,240,240)",
                showcountries=True,
                countrycolor="rgb(160,160,160)",
            ),
        )

        fig.update_xaxes(title_text=f"{unit}", row=1, col=2)

        return fig



    def plot_map_transmission_capacity(self, default_unit = None, dpi = 300, output_path = None, savefig = None):
      
        csv_path = self._results_path(False)
        df = self._get_df(csv_path)
    
        if default_unit: 
            unit = default_unit
        else: 
            unit = "MW"
        flows = []  # (from_idx, to_idx, peak_MW)
    
        for i in range(1, self.nb_country + 1):
            for j in range(i + 1, self.nb_country + 1):
                col_fwd = f"Transmission{i}to{j}.PowerOut"
                col_bwd = f"Transmission{j}to{i}.PowerOut"
    
                series_fwd = _safe_series(df.get(col_fwd))
                series_bwd = _safe_series(df.get(col_bwd))
    
                peak_fwd = series_fwd.max() if not series_fwd.empty else 0.0
                peak_bwd = series_bwd.max() if not series_bwd.empty else 0.0
    
                if peak_fwd <= 0 and peak_bwd <= 0:
                    continue
    
                # Keep the dominant direction
                if peak_fwd >= peak_bwd:
                    flows.append((i, j, peak_fwd))
                else:
                    flows.append((j, i, peak_bwd))
    
        # ── top N ────────────────────────────────────────────────────────────────
        # TOP_N = 20
        flows.sort(key=lambda x: x[2], reverse=True)
        flows_to_draw = flows[:]
        max_flow = flows_to_draw[0][2] if flows_to_draw else 1.0
    
        labels = [
            f"{self.country_names[src-1]} → {self.country_names[dst-1]}"
            for src, dst, _ in flows_to_draw
        ]
        values = [val for _, _, val in flows_to_draw]
    
        # ── figure ────────────────────────────────────────────────────────────────
        fig = make_subplots(
            rows=1, cols=1,
            specs=[[{"type": "geo"}]],
            subplot_titles=(
                f"Transmission capacities (GW)"
            ),
        )
    
        # --- curved arcs on map ---
        for src, dst, val in flows_to_draw:
            c_from = self.country_names[src - 1]
            c_to   = self.country_names[dst - 1]
            lon0, lat0 = COUNTRY_COORDS[c_from]
            lon1, lat1 = COUNTRY_COORDS[c_to]
            lons, lats = self.curved_arc(lon0, lat0, lon1, lat1, curvature=0.18)
            norm = val / max_flow
    
            fig.add_trace(
                go.Scattergeo(
                    lon=lons, lat=lats,
                    mode="lines",
                    line=dict(width=1 + 6 * norm, color="crimson"),
                    opacity=0.65,
                    hoverinfo="text",
                    text=f"{c_from} → {c_to}<br>Peak: {val:.1f} GW",
                    showlegend=False,
                ),
                row=1, col=1,
            )
    
        # --- country markers ---
        fig.add_trace(
            go.Scattergeo(
                lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
                lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
                mode="markers+text",
                marker=dict(size=6, color="black", line=dict(width=1, color="white")),
                text=self.country_names,
                textposition="top center",
                textfont=dict(size=9),
                hoverinfo="skip",
                showlegend=False,
            ),
            row=1, col=1,
        )
    
        # --- layout ---
        fig.update_layout(
            annotations=[
                dict(
                    text=(
                        "Capacity of cross-border interconnections"
                        f"<br><sup>Model: {self.model_name} </sup>"
                    ),
                    xref="paper", yref="paper",
                    x=0.5, y=1.05,
                    xanchor="center", yanchor="bottom",
                    showarrow=False,
                    font=dict(size=16),
                )
            ],
            height=650,
            margin=dict(l=0, r=20, t=80, b=0),
            geo=dict(
                scope="europe",
                projection_type="natural earth",
                showland=True,
                landcolor="rgb(240,240,240)",
                showcountries=True,
                countrycolor="rgb(160,160,160)",
                showcoastlines=True,
                coastlinecolor="rgb(180,180,180)",
            ),
    
        )
        if output_path and savefig: 
            fig.write_html(os.path.join(output_path, savefig))
            print(f"Figure saved to: {os.path.join(output_path, savefig)}")
        else:
            fig.show()


    def calculate_utilization_rate_interco(self, time_duration = 8760):
        '''Calculate utilization rates of interconnections.
        Returns:
         - self.utilization_rates_interco (dict): {itoj: value} '''
        self.utilization_rates_interco = {}

        if not self.transmission_capacity_1to1:
            self.get_transmission_capacity_by_country()
        
        for key, ts in self.transmission_1to1.items(): 
            p_moy_trans = ts.sum()/time_duration
            country1, country2 = key.split('to')
            p_max_trans = (self.transmission_capacity_1to1[f'{country1}/{country2}'] 
                           if f'{country1}/{country2}' in self.transmission_capacity_1to1 else self.transmission_capacity_1to1[f'{country2}/{country1}'])
            if p_max_trans!=0 and p_max_trans:
                self.utilization_rates_interco[key] = p_moy_trans / p_max_trans

        return self.utilization_rates_interco

    def plot_map_utilization_rate_interco(self, default_unit=None, TOP_N=40, output_path=None, savefig=None, dpi=300):
        '''Plot utilization_rates on EU map with colorscale.'''

        if not hasattr(self, 'utilization_rates_interco') or not self.utilization_rates_interco:
            self.calculate_utilization_rate_interco()

        rates = self.utilization_rates_interco

        # --- collect and sort ---
        flows = []
        for key, rate in rates.items():
            country1, country2 = key.split('to')
            flows.append((country1, country2, rate))

        flows.sort(key=lambda x: x[2], reverse=True)
        flows_to_draw = flows[:TOP_N]
        max_rate = flows_to_draw[0][2] if flows_to_draw else 1.0

        # --- colorscale setup ---
        colorscale = "RdYlGn_r"   # green=low, red=high utilization
        
        def rate_to_color(rate):
            """Map rate [0,1] to a hex color from the colorscale."""
            colors = pc.sample_colorscale(colorscale, [float(rate)])  # wrap in list, cast to float
            return colors[0]

        fig = make_subplots(
            rows=1, cols=1,
            column_widths=[0.8],
            specs=[[{"type": "geo"}]]
        )

        # --- arcs on map ---
        for country1, country2, rate in flows_to_draw:
            c_from = self.country_names[int(country1) - 1]
            c_to   = self.country_names[int(country2) - 1]
            lon0, lat0 = COUNTRY_COORDS[c_from]
            lon1, lat1 = COUNTRY_COORDS[c_to]
            lon, lat = self.curved_arc(lon0, lat0, lon1, lat1, curvature=0.15)

            color = rate_to_color(rate)

            fig.add_trace(
                go.Scattergeo(
                    lon=lon,
                    lat=lat,
                    mode="lines",
                    line=dict(
                        width=1 + 5 * rate / max_rate,
                        color=color,
                    ),
                    opacity=0.85,
                    hoverinfo="text",
                    text=f"{c_from} → {c_to}<br>{rate * 100:.1f}%",
                    showlegend=False,
                ),
                row=1, col=1,
            )

        # --- invisible scatter for colorbar ---
        fig.add_trace(
            go.Scattergeo(
                lon=[None],
                lat=[None],
                mode="markers",
                marker=dict(
                    size=0,
                    color=[0, 1],               # dummy range
                    colorscale=colorscale,
                    cmin=0,
                    cmax=1,
                    colorbar=dict(
                        title=dict(
                            text="Utilization<br>Rate",
                            side="right",
                            font=dict(size=13),
                        ),
                        thickness=15,
                        len=0.6,
                        x=1.01,
                        tickformat=".0%",
                        tickvals=[0, 0.25, 0.5, 0.75, 1.0],
                        ticktext=["0%", "25%", "50%", "75%", "100%"],
                        outlinewidth=1,
                    ),
                    showscale=True,
                ),
                showlegend=False,
            ),
            row=1, col=1,
        )

        # --- country markers ---
        fig.add_trace(
            go.Scattergeo(
                lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
                lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
                mode="markers+text",
                marker=dict(size=6, color="black"),
                text=self.country_names,
                textposition="top center",
                showlegend=False,
            ),
            row=1, col=1,
        )

        # --- layout ---
        fig.update_layout(
            annotations=[
                dict(
                    text=(
                        "Utilization rate of European cross-border interconnections"
                        f"<br><sup>Model: {self.model_name} — Top {TOP_N} flows</sup>"
                    ),
                    xref="paper", yref="paper",
                    x=0.5, y=1.05,
                    xanchor="center", yanchor="bottom",
                    showarrow=False,
                    font=dict(size=16),
                )
            ],
            height=650,
            margin=dict(l=0, r=20, t=80, b=0),
            geo=dict(
                scope="europe",
                projection_type="natural earth",
                showland=True,
                landcolor="rgb(243,243,243)",
                showocean=True,
                oceancolor="rgb(220,235,245)",
                showcountries=True,
                countrycolor="rgb(160,160,160)",
                showframe=False,
            ),
        )

        fig.show()

        if output_path and savefig:
            fig.write_image(os.path.join(output_path, savefig), scale=dpi / 96)
            print(f"Figure saved to: {os.path.join(output_path, savefig)}")

    
    def plot_map_transmission_with_utilization(self, default_unit=None, output_path = None, savefig = None, dpi = 300):
        '''Plot on the same map:
        1. Energy transmitted between countries (width)
        2. Utilization rates of transmissions (color)'''

        # --- données énergie (depuis CSV) ---
        csv_path = self._results_path(False)
        df = self._get_df(csv_path)

        energy_flows = {}
        for i in range(1, self.nb_country + 1):
            for j in range(1, self.nb_country + 1):
                if i == j:
                    continue
                col = f"Transmission{j}to{i}.PowerOut"
                series = _safe_series(df.get(col))
                if not series.empty:
                    total = series.sum()
                    if total > 0:
                        key = f"{j}to{i}"
                        energy_flows[key] = total

        # --- utilization rate ---
        if not hasattr(self, 'utilization_rates_interco') or not self.utilization_rates_interco:
            self.calculate_utilization_rate_interco()
        rates = self.utilization_rates_interco
        # print(rates)
        # --- agrégation des deux valeurs dans un dictionnaire ---
        flows = []
        for key, energy in energy_flows.items():
            rate = rates.get(key) or rates.get(
                f"{'to'.join(reversed(key.split('to')))}",  # essai sens inverse
                None
            )
            if rate is not None:
                c_from, c_to = key.split('to')
                flows.append((c_from, c_to, energy, rate))

        # --- tri par énergie, top N ---
        TOP_N = 20
        flows.sort(key=lambda x: x[2], reverse=True)
        flows_to_draw = flows[:TOP_N]

        max_energy = flows_to_draw[0][2] if flows_to_draw else 1.0

        unit = default_unit or "MWh"

        # --- colorscale -----
        def rate_to_rgb(rate, cmap_name="RdYlGn_r", vmin=0, vmax=0.7):
            cmap = plt.get_cmap(cmap_name)
            norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
            r, g, b, _ = cmap(norm(rate))
            return f"rgba({int(r*255)},{int(g*255)},{int(b*255)},0.85)"
        
        fig = go.Figure()

        # --- arcs ---
        for j, i, energy, rate in flows_to_draw:
            c_from = self.country_names[int(j) - 1]
            c_to   = self.country_names[int(i) - 1]
            lon0, lat0 = COUNTRY_COORDS[c_from]
            lon1, lat1 = COUNTRY_COORDS[c_to]
            lon, lat = self.curved_arc(lon0, lat0, lon1, lat1, curvature=0.15)

            fig.add_trace(
                go.Scattergeo(
                    lon=lon,
                    lat=lat,
                    mode="lines",
                    line=dict(
                        width=1 + 7 * energy / max_energy,   # épaisseur = énergie
                        color=rate_to_rgb(rate),              # couleur = taux utilisation
                    ),
                    opacity=0.85,
                    hoverinfo="text",
                    text=(
                        f"{c_from} → {c_to}<br>"
                        f"Énergie : {energy:.0f} {unit}<br>"
                        f"Utilisation : {rate * 100:.1f}%"
                    ),
                    showlegend=False,
                )
            )
        print(flows_to_draw)
        # --- marqueurs pays ---
        fig.add_trace(
            go.Scattergeo(
                lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
                lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
                mode="markers+text",
                marker=dict(size=6, color="black"),
                text=self.country_names,
                textposition="top center",
                showlegend=False,
            )
        )
        fig.update_traces(marker_line_width=2.0, selector=dict(type='choropleth'))
        # --- layout ---
        fig.update_layout(
            title="Flux d'énergie transmis & taux d'utilisation des interconnexions",
            height=650,
            geo=dict(
                scope="europe",
                projection_type="natural earth",
                showland=True,
                landcolor="rgb(240,240,240)",
                showcountries=True,
                countrycolor="rgb(160,160,160)",
            )
        )

        fig.show()

        if output_path and savefig: 
            fig.savefig(os.path.join(output_path, savefig), dpi=dpi, bbox_inches="tight")
            print(f"Figure saved to: {os.path.join(output_path, savefig)}")


    def _bearing(self, lon0, lat0, lon1, lat1):
        """Compass bearing (degrees) from point 0 to point 1, for arrow rotation."""
        import math
        d_lon = math.radians(lon1 - lon0)
        lat0_r = math.radians(lat0)
        lat1_r = math.radians(lat1)
        x = math.sin(d_lon) * math.cos(lat1_r)
        y = (math.cos(lat0_r) * math.sin(lat1_r)
            - math.sin(lat0_r) * math.cos(lat1_r) * math.cos(d_lon))
        return (math.degrees(math.atan2(x, y)) + 360) % 360


    def plot_bar_import_export(self, specified_unit = None, output_path=None, savefig = None, dpi = 300):
        """Bar chart empilé import / export total par pays."""
        
        unit = specified_unit if specified_unit else 'GW'
        csv_path = self._results_path(False)
        df = self._get_df(csv_path)

        exports = {c: 0.0 for c in self.country_names}
        imports = {c: 0.0 for c in self.country_names}

        for i in range(1, self.nb_country + 1):
            for j in range(1, self.nb_country + 1):
                if i == j:
                    continue
                col = f"Transmission{j}to{i}.PowerOut"
                series = _safe_series(df.get(col))
                if not series.empty:
                    total = series.sum()
                    if total > 0:
                        exports[self.country_names[j - 1]] += total
                        imports[self.country_names[i - 1]] += total

        # --- sort countries by net export (export - import) ---
        countries = self.country_names
        countries_sorted = sorted(
            countries,
            key=lambda c: exports[c] - imports[c],
            reverse=True,
        )

        exp_vals = [exports[c] / 1e3 for c in countries_sorted]   # TWh
        imp_vals = [-imports[c] / 1e3 for c in countries_sorted]  # negative for visual

        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                name="Export",
                x=countries_sorted,
                y=exp_vals,
                marker_color="crimson",
                hovertemplate="%{x}<br>Export: %{y:.2f} TWh<extra></extra>",
            )
        )

        fig.add_trace(
            go.Bar(
                name="Import",
                x=countries_sorted,
                y=imp_vals,
                marker_color="steelblue",
                hovertemplate="%{x}<br>Import: %{customdata:.2f} TWh<extra></extra>",
                customdata=[imports[c] / 1e3 for c in countries_sorted],
            )
        )

        # net balance line
        net_vals = [exports[c] / 1e6 - imports[c] / 1e3 for c in countries_sorted]
        fig.add_trace(
            go.Scatter(
                name="Net balance",
                x=countries_sorted,
                y=net_vals,
                mode="markers+lines",
                marker=dict(size=7, color="black"),
                line=dict(dash="dot", color="black", width=1.5),
                hovertemplate="%{x}<br>Net: %{y:.2f} TWh<extra></extra>",
            )
        )

        fig.update_layout(
            title="Total Import / Export by Country",
            barmode="relative",
            xaxis_title="Country",
            yaxis_title=f"Energy (TWh)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
            height=550,
        )

        fig.add_hline(y=0, line_width=1, line_color="gray")

        # fig.show()
        if output_path and savefig: 
            fig.savefig(os.path.join(output_path, savefig), dpi=dpi, bbox_inches="tight")
            print(f"Figure saved to: {os.path.join(output_path, savefig)}")

        return fig
    
    def plot_map_renewable_capacity(self, default_unit=None):

        unit = default_unit or "GW"

        csv_path = self._results_path(False)
        df = self._get_df(csv_path)

        # ── Collect peak capacity per country ─────────────────────────────────────
        solar_cap = dict(zip(self.country_names, self.pv_cap))
        wind_cap  = dict(zip(self.country_names, self.wind_cap))

        # ── Normalisation pour la hauteur des barres ──────────────────────────────
        max_cap = max(
            max(solar_cap.values(), default=1.0),
            max(wind_cap.values(),  default=1.0),
        )
        BAR_MAX_PX   = 10   # hauteur max en degrés lat (~proxy pixels Plotly)
        BAR_WIDTH_PX = 0.4  # largeur d'une barre en degrés lon

        # ── Figure ────────────────────────────────────────────────────────────────
        fig = go.Figure()

        for name in self.country_names:
            lon0, lat0 = COUNTRY_COORDS[name]
            sol = solar_cap.get(name, 0.0)
            win = wind_cap.get(name, 0.0)

            h_sol = BAR_MAX_PX * sol / max_cap
            h_win = BAR_MAX_PX * win / max_cap

            # Barre solaire (gauche, orange)
            x_sol = lon0 - BAR_WIDTH_PX
            if sol > 0:
                fig.add_trace(go.Scattergeo(
                    lon=[x_sol, x_sol, x_sol + BAR_WIDTH_PX,
                        x_sol + BAR_WIDTH_PX, x_sol],
                    lat=[lat0, lat0 + h_sol, lat0 + h_sol, lat0, lat0],
                    fill="toself",
                    fillcolor="rgba(255,165,0,0.75)",
                    line=dict(color="rgba(200,120,0,0.9)", width=0.5),
                    mode="lines",
                    hoverinfo="text",
                    text=f"{name}<br>☀ Solaire: {sol:.1f} {unit}",
                    showlegend=False,
                ))

            # Barre éolienne (droite, bleu)
            x_win = lon0 + BAR_WIDTH_PX * 0.2
            if win > 0:
                fig.add_trace(go.Scattergeo(
                    lon=[x_win, x_win, x_win + BAR_WIDTH_PX,
                        x_win + BAR_WIDTH_PX, x_win],
                    lat=[lat0, lat0 + h_win, lat0 + h_win, lat0, lat0],
                    fill="toself",
                    fillcolor="rgba(50,130,220,0.75)",
                    line=dict(color="rgba(20,80,170,0.9)", width=0.5),
                    mode="lines",
                    hoverinfo="text",
                    text=f"{name}<br>💨 Éolien: {win:.1f} {unit}",
                    showlegend=False,
                ))

        # ── Marqueurs pays ────────────────────────────────────────────────────────
        fig.add_trace(go.Scattergeo(
            lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
            lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
            mode="markers+text",
            marker=dict(size=4, color="black"),
            text=self.country_names,
            textposition="bottom center",
            textfont=dict(size=8),
            hoverinfo="skip",
            showlegend=False,
        ))

        # ── Traces de légende ─────────────────────────────────────────────────────
        fig.add_trace(go.Scattergeo(
            lon=[None], lat=[None],
            mode="markers",
            marker=dict(size=10, color="rgba(255,165,0,0.75)",
                        symbol="square", line=dict(color="rgba(200,120,0,0.9)", width=1)),
            name=f"Solaire ({unit})",
        ))
        fig.add_trace(go.Scattergeo(
            lon=[None], lat=[None],
            mode="markers",
            marker=dict(size=10, color="rgba(50,130,220,0.75)",
                        symbol="square", line=dict(color="rgba(20,80,170,0.9)", width=1)),
            name=f"Éolien ({unit})",
        ))

        # ── Annotation sur la normalisation ──────────────────────────────────────
        fig.add_annotation(
            text=f"Hauteur des barres proportionnelle à la capacité de pointe — max = {max_cap:.1f} {unit}",
            xref="paper", yref="paper",
            x=0.01, y=0.01,
            showarrow=False,
            font=dict(size=10, color="gray"),
            align="left",
        )

        # ── Layout ────────────────────────────────────────────────────────────────
        fig.update_layout(
            title="Capacités solaire et éolienne installées par pays (pic de production)",
            height=700,
            showlegend=True,
            legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)"),
            geo=dict(
                scope="europe",
                projection_type="natural earth",
                showland=True,
                landcolor="rgb(240,240,240)",
                showcountries=True,
                countrycolor="rgb(160,160,160)",
                showcoastlines=True,
                coastlinecolor="rgb(180,180,180)",
                showocean=True,
                oceancolor="rgb(220,235,250)",
            ),
            margin=dict(l=0, r=0, t=50, b=30),
        )

        fig.show()

    def plot_map_unmet(self, default_unit=None):
        unit = default_unit or "GW"

        csv_path = self._results_path(False)
        df = self._get_df(csv_path)

        # ── Collect unmet energy by country ──────────────────────────────────────
        unmet_energies = [
            (self.energies[str(i)]['E_notcovered'] + self.energies[str(i)]['E_expensive'])
            for i in range(1, len(self.country_names) + 1)
        ]
        dict_unmet = dict(zip(self.country_names, unmet_energies))

        relative_unmet_energies = []
        for i in range(0, len(self.country_names)):
            e_load = self.energies[str(i + 1)]['E_load']
            if e_load != 0:
                relative_unmet_energies.append(
                    (self.energies[str(i + 1)]['E_notcovered'] + self.energies[str(i + 1)]['E_expensive'])
                    / e_load * 100
                )
            else:
                relative_unmet_energies.append(0)
        dict_unmet_relative = dict(zip(self.country_names, relative_unmet_energies))

        # ── Shared settings ───────────────────────────────────────────────────
        geo_settings = dict(
            scope="europe",
            showframe=False,
            showcoastlines=True,
            coastlinecolor="gray",
            showland=True,
            landcolor="lightgray",
            showocean=True,
            oceancolor="aliceblue",
            projection_type="natural earth",
        )

        colorscale = [
            [0.0, "#d4f1c0"],
            [0.5, "#f7c948"],
            [1.0, "#d62728"],
        ]

        # ── Figure with 2 separate subplots ───────────────────────────────────
        fig = make_subplots(
            rows=1, cols=2,                                      
            specs=[[{"type": "choropleth"}, {"type": "choropleth"}]],
            subplot_titles=[
                f"Absolute Unmet Energy ({unit}h)",
                "Relative Unmet Energy (% of load)"
            ]
        )

        # ── Map 1 — Absolute ──────────────────────────────────────────────────────
        fig.add_trace(go.Choropleth(
            locations=self.country_names,
            locationmode="country names",
            z=[dict_unmet[c] for c in self.country_names],
            colorscale=colorscale,
            colorbar=dict(
                title=dict(text=f"{unit}h", side="right"),
                thickness=12,
                len=0.5,
                x=0.46,          
            ),
            hovertemplate="<b>%{location}</b><br>Unmet: %{z:.2f} " + unit + "h<extra></extra>",
            showscale=True,
            geo="geo",           # explicitly bound to geo1
        ), row=1, col=1)

        fig.add_trace(go.Scattergeo(
            lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
            lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
            mode="markers+text",
            marker=dict(size=4, color="black"),
            text=[f"{dict_unmet[c]:.1f}" for c in self.country_names],
            textposition="bottom center",
            textfont=dict(size=7),
            hoverinfo="skip",
            showlegend=False,
            geo="geo",   # explicitly bound to geo1        
        ), row=1, col=1)

        # ──  Map 2 - Relative ──────────────────────────────────────────────────────
        fig.add_trace(go.Choropleth(
            locations=self.country_names,
            locationmode="country names",
            z=[dict_unmet_relative[c] for c in self.country_names],
            colorscale=colorscale,
            zmin=0,
            zmax=max(dict_unmet_relative.values()),
            colorbar=dict(
                title=dict(text="%", side="right"),
                thickness=12,
                len=0.5,
                x=1.01,          # position right colorbar
            ),
            hovertemplate="<b>%{location}</b><br>Unmet: %{z:.1f}%<extra></extra>",
            showscale=True,
            geo="geo2",       
        ), row=1, col=2)

        fig.add_trace(go.Scattergeo(
            lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
            lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
            mode="markers+text",
            marker=dict(size=4, color="black"),
            text=[f"{dict_unmet_relative[c]:.1f}%" for c in self.country_names],
            textposition="bottom center",
            textfont=dict(size=7),
            hoverinfo="skip",
            showlegend=False,
            geo="geo2",          
        ), row=1, col=2)

        # ── Layout ───────────────────────────────────
        fig.update_layout(
            annotations=[
                dict(
                    text=f"Unmet Energy by Country<br><sup>Model: {self.model_name}</sup>",
                    xref="paper", yref="paper",
                    x=0.5, y=1.05,
                    xanchor="center", yanchor="bottom",
                    showarrow=False,
                    font=dict(size=16)
                )
            ],
            height=550,
            margin=dict(l=0, r=0, t=80, b=0),  # increase top margin
            geo=dict(**geo_settings),
            geo2=dict(**geo_settings),
        )
        fig.show()

    def plot_map_utilization_rate_disp(self, default_unit=None):
        unit = default_unit or "GW"

        csv_path = self._results_path(False)
        df = self._get_df(csv_path)

        # ── Collect unmet energy by country ──────────────────────────────────────
        unmet_rate = []
        for i in range(1, len(self.country_names) + 1):
            tot_unmet_ts = self.expensive_grid_ts[str(i)].copy()+self.expensive_grid_ts[str(i)].copy()
            unmet_cap = tot_unmet_ts.max()
            utilization_rate_ts = tot_unmet_ts/unmet_cap*100
            average_utilization_rate = utilization_rate_ts.sum()/len(utilization_rate_ts)
            unmet_rate.append(average_utilization_rate)

        dict_unmet_rate = dict(zip(self.country_names, unmet_rate))

        # ── Shared settings ───────────────────────────────────────────────────
        geo_settings = dict(
            scope="europe",
            showframe=False,
            showcoastlines=True,
            coastlinecolor="gray",
            showland=True,
            landcolor="lightgray",
            showocean=True,
            oceancolor="aliceblue",
            projection_type="natural earth",
        )

        colorscale = [
            [0.0, "#d4f1c0"],
            [0.5, "#f7c948"],
            [1.0, "#d62728"],
        ]

        fig = go.Figure()

        # ── Utilization rate ──────────────────────────────────────────────────────
        fig.add_trace(go.Choropleth(
            locations=self.country_names,
            locationmode="country names",
            z=[dict_unmet_rate[c] for c in self.country_names],
            colorscale=colorscale,
            zmin=0,
            zmax=max(dict_unmet_rate.values()),
            colorbar=dict(
                title=dict(text="%", side="right"),
                thickness=12,
                len=0.5,
                x=1.01,          # position right colorbar
            ),
            hovertemplate="<b>%{location}</b><br>Utilization rate: %{z:.1f}%<extra></extra>",
            showscale=True,
            geo="geo",       
        ))

        fig.add_trace(go.Scattergeo(
            lon=[COUNTRY_COORDS[c][0] for c in self.country_names],
            lat=[COUNTRY_COORDS[c][1] for c in self.country_names],
            mode="markers+text",
            marker=dict(size=4, color="black"),
            text=[f"{dict_unmet_rate[c]:.1f}%" for c in self.country_names],
            textposition="bottom center",
            textfont=dict(size=7),
            hoverinfo="skip",
            showlegend=False,
            geo="geo",          
        ))

        # ── Layout ───────────────────────────────────
        fig.update_layout(
            title=dict(text="Unmet Utilization Rate by Country", x=0.5),
            height=550,
            margin=dict(l=0, r=0, t=60, b=0),
            geo=dict(**geo_settings),
        )

        fig.show()
