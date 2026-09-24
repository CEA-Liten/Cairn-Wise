# **🌍 EU Power System Optimization with Planetary Boundaries**

---

## **📌 Overview**
This **Streamlit-based application** provides an interface to **build, optimize, and analyze multi-country electricity systems** under **Planetary Boundaries (PB) constraints** using **CAIRN **.

The tool allows users to:
✅ **Configure** energy system models for European countries.
✅ **Apply environmental constraints** (e.g., climate change, eutrophication) based on **Planetary Boundaries**.
✅ **Optimize** residual energy and capacity to maximise renewable energy service.
✅ **Visualize** results (Sankey diagrams, time-series plots, capacity mixes).
✅ **Cache and retrieve** optimization results for later analysis.

---
## 🚀 How to Run
### Prerequisites
- Python ≥ 3.13
- cairnopen: download appropriate wheel 
- Required packages (install via pip): ```pip install requirements.txt [cairnopen].whl```


## Running the App
- Clone the repository (or download the files).
- Place all required data files in the correct directories (see File Structure).
- Run Streamlit: ```streamlit run app_models_interco_EU.py```
- Open the app in your browser (default: http://localhost:8501)

---

## **🔧 Features**

--

### **1️⃣ Study Configuration**
- Define **study name**, **model name**, and **file paths** (population, time-series, planetary boundaries data).

---

### **2️⃣ Country Selection**
- Choose from **predefined country groups** (Western Europe, EU27, All Europe).
- Manually select **individual countries** from a full list.
---

### **3️⃣ Select Constraints**
- Set **transmission constraints** (GW.km) for inter-country electricity exchanges.
- Set **demand reduction**
- Chose allocation method to define the **Share of Safe Operating Space** for EU power systems. 

---

### **4️⃣ Model Building & Optimization**
The app supports **two optimization steps**:
- **Objective 1**: Minimize **unmet electricity demand** while respecting PB constraints.
- **Objective 2**: Minimize **total unmet capacity** while:
  - Respecting **PB constraints**.
  - Ensuring **unmet energy is close to the optimum* (based on Step 1 results).
- **Outputs**:
  - Optimal **installed capacities** (wind, solar, etc.).
  - **Updated energy mix** with new capacities.
---

### **5️⃣ Results Visualization**
- **🌍 Planetary Boundaries Compliance**:
  - Bar chart showing **relative impacts vs. PB limits**.
- **🏗️ Installed Capacities**:
  - Breakdown of **wind, solar, and dispatchable capacities** per country.
- **📊 Electricity Mix**:
  - Pie charts showing **energy sources** per country.
- **🌊 Energy Flow (Sankey Diagram)**:
  - Visualization of **energy exchanges** between countries.
- **📈 Time-Series Plots**:
  - **Demand vs. Supply** per country.
  - **Production stack** (wind, solar, etc.) over time.
- **📈 Interconnections Plots**:
  - **EU map with energy fluxes**.
  - **Bar chart** with main exchanges
- **📈 Gini Plots**

---

### **6️⃣ Caching & Export**
- **Save optimization results**.
- **Retrieve cached results** for later analysis (via `st.session_state`).

---

## 📝 Workflow Example
### 1️⃣ Configure Study
- Set study name = europe_pb_optimization.
- Select countries : either check one of available boxes or manually select countries 

### 2️⃣ Modify energy demand levels
- Chose level of energy demand for each country : either demand reduction or increase. 

### 3️⃣ Choose Share of Safe Operating Space (SoSOS) 
- Select:
  - Grandfathering
  - EPC+GVA
  - EPC+DLS

### 4️⃣ Chose interconections limit  
- Set the limit using the slider

### 5️⃣ Build & Run Model
- Click Build & Run 

### 6️⃣ Visualize Results
- Click 📊 Plot Results to see:
  - PB impact (bar chart).
  - Installed capacities (bar chart).
  - Electricity mix (pie charts).
  - Sankey diagram (energy flows).
  - Time-series plots (demand vs. supply).
  - Interconnections map. 
  - Import/Export bar chart. 

### 7️⃣ Save Results
- Enter a label (e.g., eu_test).
- Click 💾 Save this page's results to cache.

'''
## ** DATA Source**
- Time series: `data\time_series_normalized_2015.csv`
    - Consumption: consumption data was retrieved from Brinkerink, Maarten, and Paul Deane. 2020. “PLEXOS-World 2015.” Harvard Dataverse. https://doi.org/10.7910/DVN/CBYXBY and normalized. 
    - Production data: we created PV and wind time series by processing and aggregating data from Cheng-Ta Chu, Adam D. Hawkes,A geographic information system-based global variable renewable potential assessment using spatially resolved simulation, Energy, Volume 193, 2020, 116630, ISSN 0360-5442, https://doi.org/10.1016/j.energy.2019.116630.

## **📞 Support**
For questions, bugs and suggestions, reach out to Justine Duval at justine.duval@cea.fr
