import os
import tempfile
import subprocess
import time
import hashlib
import csv
import pandas as pd
import streamlit as st

def create_directory_if_not_exists(directory):
    """Create a directory if it does not exist."""
    os.makedirs(directory, exist_ok=True)

def load_trace(trace_file):
    """Load the existing trace data from a CSV file."""
    if os.path.exists(trace_file):
        return pd.read_csv(trace_file, delimiter=';')
    return pd.DataFrame()

def nb_countries_match(row, n):
     if int(row.get("number_countries", 0)) == n:
            print('number_countries is not matching')
            return True
     return False

def params_match(row, params):
    try:
        if round(float(row.get("tt", 0)), 4) != round(float(params.get("tt", 0)), 4):
            # st.text('tt is not matching')
            print('tt is not matching')
            return False
        if not pd.isna(row.get("carbon_budget")) and round(float(row.get("carbon_budget", 0)), 2) != round(float(params.get("carbon_budget", 0)), 2):
            # st.text('carbon_budget is not matching')
            print('carbon_budget is not matching')
            return False
        if not pd.isna(row.get("instant_satis")) and round(float(row.get("instant_satis", 0)), 2) != round(float(params.get("instant_satis", 0)), 2):
            # st.text('carbon_budget is not matching')
            print('instant_satis is not matching')
            return False
        if int(row.get("number_countries", 0)) != int(params.get("number_countries", 0)):
            # st.text('number_countries is not matching')
            print('number_countries is not matching')
            return False
        if row.get("countries_list", "") != ','.join(sorted(params.get("countries_list", []))):
            # st.text('countries_list are not matching')
            print('countries_list are not matching')
            return False
        if row.get("file_path", "") != params.get("file_path", ""):
            # st.text('file_path are not matching')
            print('file_path are not matching')
            return False
        if row.get("transmission_12", "") != params.get("transmission_12", "") or row.get("transmission_13", "") != params.get("transmission_13", "") or row.get("transmission_23", "") != params.get("transmission_23", ""):
            # st.text('file_path are not matching')
            print('tranmissions are not matching')
            return False
        if row.get("instant_satis_1", "") != params.get("instant_satis_1", "") or row.get("instant_satis_2", "") != params.get("instant_satis_2", "") or row.get("instant_satis_3", "") != params.get("instant_satis_3", ""):
            print('instant_satis are not matching')
            return False
        if row.get("demand_reduction_1", "") != params.get("demand_reduction_1", "") or row.get("demand_reduction_2", "") != params.get("demand_reduction_2", "") or row.get("demand_reduction_3", "") != params.get("demand_reduction_3", ""):
            print('demand reductions are not matching')
            return False
        if not pd.isna(row.get("environmental_impacts", "")) and row.get("environmental_impacts", "")!= ','.join(sorted(params.get("environmental_impacts", []))):
            st.text(row.get("environmental_impacts", ""))
            st.text(','.join(sorted(params.get("environmental_impacts", []))))
            st.text('env impacts are not matching')
            # print('env impacts are not matching')
            return False
        if row.get("reparation", "") != params.get("reparation", ""):
            return False 
        if "ta" in params:
            if pd.isna(params["ta"]):
                if pd.isna(params["ta"]) != pd.isna(row.get("ta",0)):

                    print('ta are not matching, nan values wrong')
                    return False 
            elif "ta" not in row or row.get("ta", 0) != params.get("ta", 0):
                print('ta are not matching')
                return False
        # st.text('passed')
        return True
    except Exception as e:
        st.text("Error in params_match:", e)
        return False
    
def trace_model_params_generic(file_path, model_id, params, trace_file):
    """
    Trace model parameters to a CSV file in a generic way.
    """
    # create_directory_if_not_exists(os.path.dirname(file_path))

    # Always include some standard fields
    row = {
        "file_path": file_path,
        "model_id": model_id
    }

    # Flatten params dict into row
    for k, v in params.items():
        if isinstance(v, list):
            row[k] = ','.join(map(str, sorted(v)))  # join lists as comma-separated string
        else:
            row[k] = v

    # Load existing trace if exists
    if os.path.exists(trace_file):
        trace_df = pd.read_csv(trace_file, delimiter=';')
    else:
        trace_df = pd.DataFrame()

    # Check if an identical row already exists
    match_found = False
    if not trace_df.empty:
        for _, existing_row in trace_df.iterrows():
            match = True
            for col, val in row.items():
                existing_val = existing_row.get(col)
                if pd.isna(existing_val) and pd.isna(val):
                    continue
                if str(existing_val) != str(val):
                    match = False
                    break
            if match:
                match_found = True
                break

    if not match_found:
        write_header = not os.path.exists(trace_file)
        with open(trace_file, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=row.keys(), delimiter=';')
            if write_header:
                writer.writeheader()
            writer.writerow(row)
        st.info("📌 Trace updated")
    else:
        st.info("ℹ️ Parameters already logged. Skipping duplicate trace.")

def generate_model_id(params: dict) -> str:
    param_str = '_'.join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.md5(param_str.encode()).hexdigest()    


def find_cached_model(trace_df, params, size_match_check=True):
    """Check if a model with matching params exists in the trace."""
    match_df = pd.DataFrame()
    size_match = False
    model_size_match_df = pd.DataFrame()

    if not trace_df.empty:
        matched_rows = [i for i, row in trace_df.iterrows() if params_match(row, params)]

        if matched_rows:
            match_df = trace_df.loc[matched_rows]
            st.dataframe(match_df)
            
        elif size_match_check:
            model_size_match = [i for i, row in trace_df.iterrows() if nb_countries_match(row, params["number_countries"])]
            if model_size_match:
                model_size_match_df = trace_df.loc[model_size_match]
                size_match = True
    # print(match_df)
    if not match_df.empty:
        
        model_id = match_df.iloc[0]["model_id"]
        file_path = match_df.iloc[0]["file_path"]
        result_file_path = os.path.join(file_path, f"{model_id}_results_Results.csv")

        return os.path.exists(result_file_path), os.path.exists(file_path), model_id, result_file_path, size_match, model_size_match_df

    return False, False, params.get("model_id"), "", size_match, model_size_match_df
