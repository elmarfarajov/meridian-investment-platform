"""The equinoxes, computed rather than approximated.

Japan's Vernal and Autumnal Equinox Days fall on whatever calendar day, in Tokyo, the
Sun crosses the equator. The Cabinet announces them a year ahead from the National
Astronomical Observatory's ephemeris, so a calendar that must be right for any year
has to do the astronomy.

The usual shortcut, ``int(20.8431 + 0.242194 * (year - 1980) - (year - 1980) // 4)``, is
right most of the time. Near midnight it can be a day out, and a wrong equinox
misplaces a settlement date. This module uses Meeus, *Astronomical Algorithms*
(2nd edition, 1998), chapter 27. That is a mean equinox from a polynomial, corrected
by 24 periodic terms, and good to about a minute for 1951-2050. When two published
calendars disagree about an equinox, this is the arbiter.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Literal

Season = Literal["march", "september"]

JST = timezone(timedelta(hours=9), "JST")

# Meeus table 27.A (years 1000-3000): the mean equinox as a polynomial in millennia from 2000
_MEAN: dict[str, tuple[float, float, float, float, float]] = {
    "march": (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),
    "september": (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),
}

# Meeus table 27.C: amplitude A, phase B (degrees) and rate C (degrees per Julian century)
_PERIODIC: tuple[tuple[int, float, float], ...] = (
    (485, 324.96, 1934.136),
    (203, 337.23, 32964.467),
    (199, 342.08, 20.186),
    (182, 27.85, 445267.112),
    (156, 73.14, 45036.886),
    (136, 171.52, 22518.443),
    (77, 222.54, 65928.934),
    (74, 296.72, 3034.906),
    (70, 243.58, 9037.513),
    (58, 119.81, 33718.147),
    (52, 297.17, 150.678),
    (50, 21.02, 2281.226),
    (45, 247.54, 29929.562),
    (44, 325.15, 31555.956),
    (29, 60.93, 4443.417),
    (18, 155.12, 67555.328),
    (17, 288.79, 4562.452),
    (16, 198.04, 62894.029),
    (14, 199.76, 31436.921),
    (12, 95.39, 14577.848),
    (12, 287.11, 31931.756),
    (12, 320.81, 34777.259),
    (9, 227.73, 1222.114),
    (8, 15.45, 16859.074),
)

_J2000 = 2451545.0
_UNIX_EPOCH_JD = 2440587.5


def delta_t_seconds(year: float) -> float:
    """Terrestrial minus Universal Time, by the Espenak-Meeus polynomials (NASA, 2006).

    Between 1990 and 2060 it is about a minute. It matters only when an equinox falls
    within a minute of midnight in Tokyo.
    """
    if year < 2005:
        t = year - 2000
        return 63.86 + 0.3345 * t - 0.060374 * t**2 + 0.0017275 * t**3 + 0.000651814 * t**4 + 0.00002373599 * t**5
    if year < 2050:
        t = year - 2000
        return 62.92 + 0.32217 * t + 0.005589 * t**2
    u = (year - 1820) / 100
    return -20 + 32 * u**2 - 0.5628 * (2150 - year)


def equinox_jde(year: int, season: Season) -> float:
    """The Julian Ephemeris Day of the equinox, in Terrestrial Time."""
    if not 1000 <= year <= 3000:
        raise ValueError("Meeus table 27.A covers the years 1000 to 3000")
    y = (year - 2000) / 1000
    a0, a1, a2, a3, a4 = _MEAN[season]
    jde0 = a0 + a1 * y + a2 * y**2 + a3 * y**3 + a4 * y**4
    t = (jde0 - _J2000) / 36525
    w = math.radians(35999.373 * t - 2.47)
    dlambda = 1 + 0.0334 * math.cos(w) + 0.0007 * math.cos(2 * w)
    s = sum(amplitude * math.cos(math.radians(phase + rate * t)) for amplitude, phase, rate in _PERIODIC)
    return jde0 + 0.00001 * s / dlambda


def equinox(year: int, season: Season) -> datetime:
    """The instant of the equinox in UTC."""
    jde = equinox_jde(year, season)
    jd_ut = jde - delta_t_seconds(year) / 86400
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=jd_ut - _UNIX_EPOCH_JD)


def equinox_day(year: int, season: Season, zone: timezone = JST) -> date:
    """The calendar day of the equinox in a time zone - Tokyo by default."""
    return equinox(year, season).astimezone(zone).date()
