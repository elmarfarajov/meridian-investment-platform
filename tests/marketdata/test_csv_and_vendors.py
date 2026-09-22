"""Flat files, vendor panels and source hierarchies."""

from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from meridian.core.exceptions import ValidationError
from meridian.marketdata.providers import (
    CsvProvider,
    InstrumentSpec,
    ProviderError,
    StaticProvider,
    SyntheticMarket,
    VendorProfile,
    WaterfallProvider,
    load,
    read_fx,
    read_quotes,
    vendor_panel,
    write_fx,
    write_quotes,
)
from meridian.marketdata.quotes import FxQuote, MarketDataset, Quote

D1, D2 = date(2026, 5, 4), date(2026, 5, 5)


def quote(day: date, close: str, source: str, instrument: str = "X") -> Quote:
    return Quote(instrument_id=instrument, day=day, close=Decimal(close), currency="USD", source=source)


# ---------------------------------------------------------------------------- CSV
def test_quotes_round_trip_through_csv(tmp_path: Path):
    quotes = [
        Quote(
            instrument_id="X",
            day=D1,
            close=Decimal("101.25"),
            currency="USD",
            source="desk",
            bid=Decimal("101.20"),
            ask=Decimal("101.30"),
            volume=1500,
        ),
        quote(D2, "102.00", "desk"),
    ]
    path = tmp_path / "prices.csv"
    assert write_quotes(path, quotes) == 2
    loaded = read_quotes(path)
    assert loaded.is_clean
    assert loaded.quotes == quotes


def test_bad_lines_are_reported_with_line_numbers_not_dropped_silently(tmp_path: Path):
    path = tmp_path / "vendor.csv"
    path.write_text(
        "date,instrument_id,close,currency\n"
        "2026-05-04,X,101.25,USD\n"
        "04/05/2026,X,101.30,USD\n"
        "2026-05-06,X,abc,USD\n"
        "2026-05-07,,99,USD\n",
        encoding="utf-8",
    )
    result = read_quotes(path)
    assert result.lines_read == 4
    assert result.accepted == 1
    assert [issue.line for issue in result.issues] == [3, 4, 5]
    assert "ISO 8601" in result.issues[0].message
    assert str(result.issues[0]).startswith("vendor.csv:3:")
    assert result.quotes[0].source == "vendor"  # defaults to the file name


def test_strict_mode_stops_at_the_first_bad_line(tmp_path: Path):
    path = tmp_path / "strict.csv"
    path.write_text("date,instrument_id,close,currency\n2026-13-01,X,1,USD\n", encoding="utf-8")
    with pytest.raises(ProviderError, match=r"strict\.csv:2"):
        read_quotes(path, strict=True)


def test_a_missing_required_column_fails_the_whole_file(tmp_path: Path):
    path = tmp_path / "broken.csv"
    path.write_text("date,instrument_id,price\n2026-05-04,X,1\n", encoding="utf-8")
    with pytest.raises(ProviderError, match="close"):
        read_quotes(path)


def test_headers_are_case_insensitive_and_a_bom_is_tolerated(tmp_path: Path):
    path = tmp_path / "excel.csv"
    path.write_text("﻿Date,Instrument_ID,Close,Currency\n2026-05-04,X,1.5,usd\n", encoding="utf-8")
    loaded = read_quotes(path)
    assert loaded.quotes[0].close == Decimal("1.5")
    assert loaded.quotes[0].currency == "USD"


def test_fx_files(tmp_path: Path):
    rates = [FxQuote(base="EUR", quote="USD", day=D1, rate=Decimal("1.0842"), source="wm")]
    path = tmp_path / "fx.csv"
    write_fx(path, rates)
    assert read_fx(path).fx == rates
    bad = tmp_path / "fx_bad.csv"
    bad.write_text("date,base,quote,rate\n2026-05-04,USD,USD,1\n", encoding="utf-8")
    assert len(read_fx(bad).issues) == 1
    with pytest.raises(ProviderError):
        read_fx(bad, strict=True)


def test_csv_provider_serves_a_date_window(tmp_path: Path):
    path = tmp_path / "p.csv"
    write_quotes(path, [quote(D1, "1", "f"), quote(D2, "2", "f"), quote(D2, "3", "f", instrument="Y")])
    fx_path = tmp_path / "fx.csv"
    write_fx(fx_path, [FxQuote(base="EUR", quote="USD", day=D1, rate=Decimal("1.1"))])
    provider = CsvProvider("files", [path], [fx_path])
    assert provider.name == "files"
    assert [item.day for item in provider.quotes(["X"], D2, D2)] == [D2]
    assert len(provider.fx_quotes(["eurusd"], D1, D2)) == 1
    assert provider.issues == []


# ---------------------------------------------------------------------------- providers
def test_load_refuses_a_backwards_window():
    with pytest.raises(ProviderError, match="before it starts"):
        load(StaticProvider("s"), ["X"], D2, D1)


def test_waterfall_takes_the_highest_ranked_source_per_day():
    primary = StaticProvider("primary", [quote(D1, "100.00", "primary")])
    backup = StaticProvider("backup", [quote(D1, "100.50", "backup"), quote(D2, "101.00", "backup")])
    waterfall = WaterfallProvider([primary, backup])
    chosen = waterfall.quotes(["X"], D1, D2)
    assert [(item.day, item.source) for item in chosen] == [(D1, "primary"), (D2, "backup")]
    assert waterfall.coverage(["X"], D1, D2) == {"primary": 1, "backup": 1}
    assert waterfall.ranking == ("primary", "backup")
    with pytest.raises(ValidationError):
        WaterfallProvider([])


def test_waterfall_for_fx():
    primary = StaticProvider("p", fx=[FxQuote(base="EUR", quote="USD", day=D1, rate=Decimal("1.1"), source="p")])
    backup = StaticProvider("b", fx=[FxQuote(base="EUR", quote="USD", day=D1, rate=Decimal("1.2"), source="b")])
    (rate,) = WaterfallProvider([primary, backup]).fx_quotes(["EURUSD"], D1, D1)
    assert rate.source == "p"


# ---------------------------------------------------------------------------- vendors
@pytest.fixture(scope="module")
def reference() -> MarketDataset:
    return (
        SyntheticMarket([InstrumentSpec("A"), InstrumentSpec("B", initial_price=30.0)], seed=2)
        .generate(date(2025, 1, 2), date(2025, 12, 31))
        .dataset
    )


def test_a_perfect_vendor_reproduces_the_reference(reference: MarketDataset):
    panel = vendor_panel(reference, [VendorProfile("mirror")])
    assert panel.close_series("A", source="mirror") == reference.close_series("A")
    first = panel.for_instrument("A")[0]
    truth = reference.for_instrument("A")[0]
    assert (first.bid, first.ask) == (truth.bid, truth.ask)


def test_vendor_habits_show_up_in_the_data(reference: MarketDataset):
    profiles = [
        VendorProfile("patchy", coverage=0.8),
        VendorProfile("stale", stale_probability=0.3),
        VendorProfile("noisy", noise_bps=20.0),
    ]
    panel = vendor_panel(reference, profiles, seed=4)
    expected = len(reference.for_instrument("A"))
    assert len(panel.for_instrument("A", source="patchy")) < 0.9 * expected
    stale = panel.close_series("A", source="stale")
    repeats = sum(1 for a, b in itertools.pairwise(stale.values) if a == b)
    assert repeats > 0.15 * len(stale)
    noisy = panel.close_series("A", source="noisy")
    truth = reference.close_series("A")
    errors = [abs(float(noisy[day] / truth[day]) - 1) * 10_000 for day in noisy.days]
    assert 5 < sum(errors) / len(errors) < 40


def test_vendor_profile_validation():
    with pytest.raises(ValidationError):
        VendorProfile("x", coverage=1.5)
    with pytest.raises(ValidationError):
        VendorProfile("x", noise_bps=-1)
