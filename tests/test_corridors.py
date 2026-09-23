"""Unit tests for the corridor engine — proportional allocation and the trailing-window lag,
verified on small synthetic inputs with hand-computed expected values."""
import pandas as pd
import pytest
from src.corridors import build_corridors


def test_proportional_allocation():
    """Single month: 60/40 import shares split across two destinations."""
    m = pd.Timestamp("2025-01-01")
    imp = pd.DataFrame({"period": [m, m], "country_iso2": ["JP", "IN"], "value_usd": [60.0, 40.0]})
    rex = pd.DataFrame({"period": [m, m], "country_iso2": ["SA", "AE"], "value_usd": [100.0, 50.0]})

    corridors, diag = build_corridors(imp, rex, lag_months=2)
    got = {(r.origin, r.dest): r.est_value for r in corridors.itertuples()}

    # shares: JP 0.6, IN 0.4  ->  applied to SA(100) and AE(50)
    assert got[("JP", "SA")] == pytest.approx(60.0)   # 0.6 * 100
    assert got[("IN", "SA")] == pytest.approx(40.0)   # 0.4 * 100
    assert got[("JP", "AE")] == pytest.approx(30.0)   # 0.6 * 50
    assert got[("IN", "AE")] == pytest.approx(20.0)   # 0.4 * 50

    # conservation: corridors must sum to total re-exports
    assert corridors["est_value"].sum() == pytest.approx(150.0)
    assert diag["attributed_pct"] == pytest.approx(1.0)


def test_trailing_window_lag():
    """The lag pulls in a prior month's imports when splitting this month's re-exports."""
    jan, feb = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-02-01")
    imp = pd.DataFrame({"period": [jan, feb], "country_iso2": ["JP", "DE"], "value_usd": [100.0, 100.0]})
    rex = pd.DataFrame({"period": [feb], "country_iso2": ["SA"], "value_usd": [100.0]})

    # lag_months=1 -> Feb window = Jan+Feb -> JP 100, DE 100 -> 50/50 split
    corridors, _ = build_corridors(imp, rex, lag_months=1)
    got = {(r.origin, r.dest): r.est_value for r in corridors.itertuples()}
    assert got[("JP", "SA")] == pytest.approx(50.0)
    assert got[("DE", "SA")] == pytest.approx(50.0)

    # lag_months=0 -> Feb window = Feb only -> DE 100 -> all to DE
    corridors0, _ = build_corridors(imp, rex, lag_months=0)
    got0 = {(r.origin, r.dest): r.est_value for r in corridors0.itertuples()}
    assert got0[("DE", "SA")] == pytest.approx(100.0)
    assert ("JP", "SA") not in got0