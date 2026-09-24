from __future__ import annotations
 
import math
from typing import Any
 
import numpy as np
import streamlit as st
 
_PERSIST_PREFIX = "_persist__"


def persistent_value(name: str, default: Any) -> Any:
    """Return the last value remembered for *name*, or *default* if none yet."""
    return st.session_state.get(_PERSIST_PREFIX + name, default)
 
 
def save_persistent(name: str) -> None:
    """
    Copies the widget's current value into a key can be restored later even if the widget itself
    disappears for a while. 
    """
    if name in st.session_state:
        st.session_state[_PERSIST_PREFIX + name] = st.session_state[name]
 
 
def safe_div(numerator: Any, denominator: Any, default: float = 0.0) -> float:
    """
    Divide two numbers, returning *default* instead of raising an error.
    """
    try:
        if numerator is None or denominator is None:
            return default
        num = float(numerator)
        den = float(denominator)
        if den == 0 or math.isnan(den) or math.isnan(num):
            return default
        result = num / den
        if math.isinf(result) or math.isnan(result):
            return default
        return result
    except (TypeError, ValueError, ZeroDivisionError):
        return default
 
 
def safe_div_series(numerator, denominator, default: float = 0.0):
    """Same idea as `safe_div` but for a pandas Series/np array."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = numerator / denominator
    return result.replace([np.inf, -np.inf], np.nan).fillna(default) if hasattr(result, "replace") else np.nan_to_num(
        result, nan=default, posinf=default, neginf=default
    )
 