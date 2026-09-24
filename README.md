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
- Define **study name**.

---

### **2️⃣ Country Selection**
- Manually select **individual countries**.
---

### **3️⃣ Select Constraints**
- Set **transmission constraints** (GW.km) for inter-country electricity exchanges.
- Set **demand reduction** levels for each country.
- Chose allocation method to define the **Share of Safe Operating Space** for EU power systems. 

---

### **4️⃣ Model Building & Optimization**
The app supports **two optimization steps**:
- **Objective 1**: Minimize **unmet electricity demand** while respecting PB constraints.
- **Objective 2**: Minimize **total unmet capacity** while:
  - Respecting **PB constraints**.
  - Ensuring **unmet energy is close to the optimum* (based on Step 1 results).
- These two objectives are optimized during the 7 `build & run`step by clicking on a single button.
- **Outputs**:
  - Optimal **installed capacities** (wind, solar) for each country.
  - **Electricity mix**
  - Interconnections map between countries.
  - ...
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
- **📈 Import/Export Plot**

---

### **6️⃣ Caching & Export**
- **Save optimization results**.
- **Retrieve cached results** in page `Saved results`.

---

## 📝 Workflow Example
### 1️⃣ Configure Study
- Set study name = europe_pb_optimization.
- Select countries : either check one of available boxes or manually select countries 

### 2️⃣ Modify energy demand levels
- Chose level of energy demand for each country : either demand reduction or increase. 

### 3️⃣ Choose a method of allocation to define a Share of Safe Operating Space (SoSOS) 
- Select:
  - Grandfathering
  - Equal per capita (EPC) + Gross Value Added (GVA)
  - Equal per capita (EPC) + Decent Living Standards (DLS)

### 4️⃣ Chose interconections limit  
- Set the upper limit using the slider

### 5️⃣ Build & Run Model
- Click Build & Run
- Solving time can be quite long depending on the solver and the constraints. 

### 6️⃣ Visualize Results
- Click 📊 Plot Results.
- See figures in the different tabs. 

### 7️⃣ Save Results
- Enter a label (e.g., eu_test).
- Click 💾 Save this page's results to cache.

'''
## **DATA Source**
- Time series: `data\time_series_normalized_2015.csv`
    - Consumption: consumption data was retrieved from Brinkerink, Maarten, and Paul Deane. 2020. “PLEXOS-World 2015.” Harvard Dataverse. https://doi.org/10.7910/DVN/CBYXBY and normalized. 
    - Production data: we created PV and wind time series by processing and aggregating data from Cheng-Ta Chu, Adam D. Hawkes,A geographic information system-based global variable renewable potential assessment using spatially resolved simulation, Energy, Volume 193, 2020, 116630, ISSN 0360-5442, https://doi.org/10.1016/j.energy.2019.116630.

## **📞 Support**
For questions, bugs and suggestions, reach out to Justine Duval at justine.duval@cea.fr
