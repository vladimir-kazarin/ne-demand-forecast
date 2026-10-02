"""Forecast error metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd


def mape(actual: pd.Series, forecast: pd.Series) -> float:
    """Mean absolute percentage error in percent, over hours where both exist."""
    a, f = actual.align(forecast, join="inner")
    mask = a.notna() & f.notna() & (a != 0)
    if not mask.any():
        raise ValueError("no overlapping non-zero hours to score")
    return float(np.mean(np.abs((a[mask] - f[mask]) / a[mask])) * 100)
