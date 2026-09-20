"""The rates, charts and extended calendar commands."""

from __future__ import annotations

from typer.testing import CliRunner

from meridian.cli import app

runner = CliRunner()


def test_curve_prints_par_zero_and_forward():
    result = runner.invoke(app, ["rates", "curve", "--tenors", "1,2,5,10", "--par", "4.18,3.95,3.90,4.15"])
    assert result.exit_code == 0
    assert "Par" in result.stdout and "Zero" in result.stdout
    assert "4.1800%" in result.stdout


def test_curve_rejects_mismatched_inputs():
    result = runner.invoke(app, ["rates", "curve", "--tenors", "1,2", "--par", "4.0"])
    assert result.exit_code == 1


def test_curve_writes_a_chart(tmp_path):
    destination = tmp_path / "curve.png"
    result = runner.invoke(
        app,
        ["rates", "curve", "--tenors", "1,2,5,10", "--par", "4.18,3.95,3.90,4.15", "--chart", str(destination)],
    )
    assert result.exit_code == 0
    assert destination.exists()


def test_bond_solves_a_yield_from_a_price():
    result = runner.invoke(
        app,
        [
            "rates",
            "bond",
            "2034-05-15",
            "--coupon",
            "4",
            "--issue",
            "2024-05-15",
            "--settlement",
            "2026-09-21",
            "--price",
            "96.79",
        ],
    )
    assert result.exit_code == 0
    assert "Yield to maturity" in result.stdout
    assert "4.500" in result.stdout
    assert "Modified duration" in result.stdout


def test_bond_prices_from_a_yield():
    result = runner.invoke(
        app,
        [
            "rates",
            "bond",
            "2036-09-18",
            "--coupon",
            "5",
            "--issue",
            "2026-09-18",
            "--settlement",
            "2026-09-18",
            "--ytm",
            "5",
            "--frequency",
            "1",
        ],
    )
    assert result.exit_code == 0
    assert "100.000000" in result.stdout


def test_bond_rejects_an_unsupported_frequency():
    result = runner.invoke(app, ["rates", "bond", "2034-05-15", "--frequency", "3"])
    assert result.exit_code == 1


def test_schedule_lists_the_periods_and_marks_the_stub():
    result = runner.invoke(app, ["rates", "schedule", "2025-02-10", "2026-05-15", "--frequency", "semi_annual"])
    assert result.exit_code == 0
    assert "stub" in result.stdout
    assert "2026-05-15" in result.stdout


def test_daycount_compares_every_convention():
    result = runner.invoke(app, ["rates", "daycount", "2026-01-15", "2026-07-15"])
    assert result.exit_code == 0
    for convention in ("ACT/360", "ACT/ACT ICMA", "BUS/252", "30E/360 ISDA"):
        assert convention in result.stdout


def test_compounding_shows_the_effective_annual_rate():
    result = runner.invoke(app, ["rates", "compounding", "--rate", "5", "--years", "10"])
    assert result.exit_code == 0
    assert "continuous" in result.stdout
    assert "5.1271" in result.stdout


def test_forward_rate_between_two_horizons():
    result = runner.invoke(app, ["rates", "forward", "1", "2"])
    assert result.exit_code == 0
    assert "1Y into 1Y" in result.stdout


def test_calendar_matrix_ranks_the_pairs():
    result = runner.invoke(app, ["calendar", "matrix", "--year", "2026", "--calendars", "XNYS,XLON,XTKS"])
    assert result.exit_code == 0
    assert "XNYS / XLON" in result.stdout


def test_calendar_ladder_shows_the_joint_calendar():
    result = runner.invoke(app, ["calendar", "ladder", "2026-12-23", "--calendars", "XNYS,XLON"])
    assert result.exit_code == 0
    assert "XNYS+XLON" in result.stdout
    assert "2026-12-29" in result.stdout


def test_holidays_now_print_their_names():
    result = runner.invoke(app, ["calendar", "holidays", "XTKS", "--year", "2026"])
    assert result.exit_code == 0
    assert "Vernal Equinox Day" in result.stdout


def test_security_validate_accepts_an_lei():
    result = runner.invoke(app, ["security", "validate", "HWUPKR0MPOU8FGXBT394", "784F5XWPLTWKTBV3E584"])
    assert result.exit_code == 0
    assert "LEI" in result.stdout
    assert "invalid" not in result.stdout


def test_charts_list_and_gallery(tmp_path):
    listed = runner.invoke(app, ["charts", "list"])
    assert listed.exit_code == 0
    assert "data-model.png" in listed.stdout

    built = runner.invoke(app, ["charts", "gallery", "--out", str(tmp_path), "--only", "money", "--dpi", "60"])
    assert built.exit_code == 0
    assert any(tmp_path.iterdir())


def test_charts_schema_writes_the_diagram(tmp_path):
    destination = tmp_path / "erd.png"
    result = runner.invoke(app, ["charts", "schema", "--out", str(destination)])
    assert result.exit_code == 0
    assert destination.exists()
