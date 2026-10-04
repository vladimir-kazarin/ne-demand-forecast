"""Input drift checks, calibrated against a year of real weekly data.

Two alerting checks target the drift that actually breaks this model:

- **Station consistency.** Each station's offset from the four-station mean is set
  by geography, so it is stable across years. A large shift in a station's average
  offset (vs the same weeks last year) means a data problem: wrong station, unit
  change, stale feed. Alert if any station's mean offset moves by >= 2.5 °C.
- **Out of range.** Tree models cannot extrapolate. Alert if more than 2% of hours
  have a temperature beyond the training range ± 2 °C.

PSI (Population Stability Index) per feature against the same weeks one year
earlier is reported as context but does not alert. Backtest over 49 weeks
(Oct 2025 - Oct 2026): raw-temperature PSI exceeded the classic 0.25 cut-off in
every week, because one week of hourly weather is effectively seven samples and
this year's weather is simply different from last year's. Forecast error, tracked
daily, is the primary alarm; these checks explain it and catch data faults early.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats

from ne_demand.features.build import TEMP_COLUMNS

CONTEXT_FEATURES = [*TEMP_COLUMNS, "temp_mean", "load_lag_48h", "load_lag_168h"]
SPREAD_SHIFT_ALERT_C = 2.5
OUT_OF_RANGE_MARGIN_C = 2.0
OUT_OF_RANGE_ALERT_SHARE = 0.02
PSI_WATCH, PSI_DRIFT = 0.10, 0.25
_EPS = 1e-4


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Population Stability Index of `current` against `reference` (quantile bins)."""
    reference, current = reference[~np.isnan(reference)], current[~np.isnan(current)]
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)[1:-1]))
    edges = np.concatenate([[-np.inf], edges, [np.inf]])
    ref = np.histogram(reference, edges)[0] / len(reference)
    cur = np.histogram(current, edges)[0] / len(current)
    ref, cur = np.clip(ref, _EPS, None), np.clip(cur, _EPS, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def psi_status(value: float) -> str:
    return "drift" if value >= PSI_DRIFT else "watch" if value >= PSI_WATCH else "stable"


def current_days(end: date, n: int = 7) -> list[date]:
    return [end - timedelta(days=i) for i in range(n)][::-1]


def seasonal_reference_days(current: list[date], pad_days: int = 14) -> list[date]:
    """The current window's dates one year earlier, padded on both sides."""
    start = current[0] - timedelta(days=364 + pad_days)  # 364 keeps weekdays aligned
    end = current[-1] - timedelta(days=364 - pad_days)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def station_spread(df: pd.DataFrame) -> pd.DataFrame:
    """Each station's temperature minus the four-station mean."""
    return df[TEMP_COLUMNS].sub(df[TEMP_COLUMNS].mean(axis=1), axis=0)


def context_table(
    reference: pd.DataFrame, current: pd.DataFrame, features: list[str] = CONTEXT_FEATURES
) -> pd.DataFrame:
    """PSI and KS per feature vs the seasonal reference (dashboard context, no alerts)."""
    rows = []
    for f in features:
        r, c = reference[f].to_numpy(float), current[f].to_numpy(float)
        r, c = r[~np.isnan(r)], c[~np.isnan(c)]
        value = psi(r, c)
        ks = stats.ks_2samp(r, c)
        rows.append(
            {
                "feature": f,
                "psi": value,
                "psi_status": psi_status(value),
                "ks_stat": float(ks.statistic),
                "ks_pvalue": float(ks.pvalue),
                "reference_mean": float(r.mean()),
                "current_mean": float(c.mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("psi", ascending=False, ignore_index=True)


@dataclass
class DriftResult:
    spread_shift_c: dict[str, float]
    out_of_range_share: float
    context: pd.DataFrame
    alerts: list[str] = field(default_factory=list)

    @property
    def drifted(self) -> bool:
        return bool(self.alerts)


def check_drift(
    reference: pd.DataFrame, current: pd.DataFrame, training_range: tuple[pd.Series, pd.Series]
) -> DriftResult:
    """reference: same weeks last year; current: this week's hourly features;
    training_range: per-station (min, max) temperature seen in training."""
    shift = (station_spread(current).mean() - station_spread(reference).mean()).abs()
    lo, hi = training_range
    t = current[TEMP_COLUMNS]
    outside = ((t < lo - OUT_OF_RANGE_MARGIN_C) | (t > hi + OUT_OF_RANGE_MARGIN_C)).any(axis=1)
    result = DriftResult(
        spread_shift_c={k.removeprefix("temp_"): float(v) for k, v in shift.items()},
        out_of_range_share=float(outside.mean()),
        context=context_table(reference, current),
    )
    worst = shift.idxmax()
    if shift.max() >= SPREAD_SHIFT_ALERT_C:
        result.alerts.append(
            f"{worst.removeprefix('temp_')} temperature moved {shift.max():.1f} °C relative to the "
            f"other stations (alert at {SPREAD_SHIFT_ALERT_C} °C): possible data fault"
        )
    if result.out_of_range_share > OUT_OF_RANGE_ALERT_SHARE:
        result.alerts.append(
            f"{result.out_of_range_share:.0%} of hours have temperatures outside the training "
            f"range ± {OUT_OF_RANGE_MARGIN_C:.0f} °C: the model is extrapolating"
        )
    return result


def inject_shift(current: pd.DataFrame, shifts: dict[str, float]) -> pd.DataFrame:
    """Add a constant to features (drift drills and the PRD acceptance test)."""
    out = current.copy()
    for feature, delta in shifts.items():
        out[feature] = out[feature] + delta
    out["temp_mean"] = out[TEMP_COLUMNS].mean(axis=1)
    return out
