"""The packaged rates history: what it covers, and that it is the published data."""

from datetime import date
from itertools import pairwise

import numpy as np
import pytest

from meridian.devtools.fetch_rates import gsw_rows, treasury_rows
from meridian.marketdata.rates_history import (
    SOURCES,
    TREASURY_TENORS,
    gsw_curve,
    illustrative_sofr_quotes,
    par_curve_on,
    treasury_matrix,
    treasury_par_yields,
)


def test_the_treasury_curve_covers_1990_to_september_2026():
    curves = treasury_par_yields()
    assert curves[0].day == date(1990, 1, 2)
    assert curves[-1].day == date(2026, 9, 30)
    assert len(curves) > 9_000
    assert all(earlier.day < later.day for earlier, later in pairwise(curves))


def test_a_published_day_reads_back_as_published():
    lehman = par_curve_on(date(2008, 9, 15))
    by_label = dict(zip(lehman.labels, lehman.yields, strict=True))
    assert by_label["3M"] == pytest.approx(0.0102)
    assert by_label["10Y"] == pytest.approx(0.0347)
    assert "20Y" in by_label and "30Y" in by_label


def test_a_tenor_appears_only_when_the_treasury_published_it():
    assert "1M" not in par_curve_on(date(1995, 6, 1)).labels  # the 1-month bill column starts in 2001
    assert "30Y" not in par_curve_on(date(2004, 6, 1)).labels  # the 30-year paused from 2002 to 2006
    assert "4M" in par_curve_on(date(2026, 9, 30)).labels


def test_a_weekend_reads_the_last_published_curve():
    assert par_curve_on(date(2026, 9, 27)).day == date(2026, 9, 25)
    with pytest.raises(LookupError):
        par_curve_on(date(1989, 12, 29))


def test_the_matrix_keeps_only_days_with_every_tenor():
    days, yields = treasury_matrix(["2Y", "10Y", "30Y"], start=date(2000, 1, 1))
    assert yields.shape == (len(days), 3)
    assert not any(date(2002, 3, 1) <= day <= date(2006, 2, 1) for day in days)


def test_the_gsw_curve_has_parameters_and_yields_for_every_day():
    parameters, yields = gsw_curve()
    assert len(parameters) == len(yields) > 9_000
    assert parameters[0].day == date(1990, 1, 2)
    missing = [item.day for item, row in zip(parameters, yields, strict=True) if not np.isfinite(row).all()]
    assert missing == [date(2008, 3, 21)]  # Good Friday 2008: the Fed published parameters but no yields
    assert all(item.tau1 > 0 for item in parameters)


def test_the_sources_are_named():
    assert "Treasury" in SOURCES["treasury"] and "FEDS 2006-28" in SOURCES["gsw"]


def test_illustrative_sofr_quotes_sit_below_treasuries_at_the_long_end():
    quotes = illustrative_sofr_quotes(date(2026, 9, 30), ["2Y", "10Y", "30Y"])
    treasury = dict(zip(par_curve_on(date(2026, 9, 30)).labels, par_curve_on(date(2026, 9, 30)).yields, strict=True))
    assert quotes[2] < treasury["30Y"] - 0.005  # negative long swap spreads
    assert quotes[0] < treasury["2Y"]


def test_the_fetcher_normalises_the_treasury_s_changing_headings():
    first = 'Date,"3 Mo","10 Yr"\n01/03/1990,7.83,7.94\n01/02/1990,7.83,7.94\n'
    later = 'Date,"1 Mo","1.5 Month","10 Yr"\n09/30/2026,4.02,4.13,5.29\n'
    rows = treasury_rows([first, later])
    assert [row["date"] for row in rows] == ["1990-01-02", "1990-01-03", "2026-09-30"]
    assert rows[-1]["6W"] == "4.13" and rows[0]["1M"] == ""
    assert set(TREASURY_TENORS) <= set(rows[0])


def test_the_fetcher_reads_the_fed_file_past_its_preamble():
    yields = ",".join(f"SVENY{t:02d}" for t in (1, 2, 3, 5, 7, 10, 15, 20, 30))
    header = f"Date,BETA0,BETA1,BETA2,BETA3,TAU1,TAU2,{yields}"
    early = "1989-12-29,1,2,3,4,5,6" + ",1" * 9
    later = "2000-01-03,3.6,1.5,3.6,9.8,1.2,8.1" + ",6.1234567" * 8 + ",NA"
    text = f"note line\n\n{header}\n{early}\n{later}\n"
    rows = gsw_rows(text)
    assert len(rows) == 1 and rows[0]["date"] == "2000-01-03"
    assert rows[0]["SVENY01"] == "6.123457" and rows[0]["SVENY30"] == "NA"
