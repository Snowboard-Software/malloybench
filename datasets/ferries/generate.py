"""Skerry Line: generated data for a fictional island ferry operator, 2022-01-01 to 2025-12-31.

build.py calls write_tables(). Every random draw comes from numpy's default_rng, one seeded
stream per stage, and every table is written in a fixed row order, so a rebuild reproduces
the row counts and content hashes recorded in manifest.json (with the numpy and duckdb
versions pinned in requirements.txt).

Clocks: the timetable and everything the booking system records are local time in the
archipelago, which keeps EU summer time (UTC+1, and UTC+2 from 02:00 on the last Sunday of
March to 03:00 on the last Sunday of October). The vessels' AIS log, which supplies actual
departure and arrival times, is UTC.

The generator works in this order: timetable (which vessel sails where and when), weather
warnings, what happened to each sailing (cancelled, diverted, delayed), demand and bookings,
fares in EUR converted to the booking currency at the booking date's rate, then refunds.
"""

from __future__ import annotations

import duckdb
import numpy as np

SEED = 4127

FIRST_DAY = np.datetime64("2022-01-01")
END_DAY = np.datetime64("2026-01-01")  # exclusive
DAYS = np.arange(FIRST_DAY, END_DAY)
RATE_FIRST_DAY = np.datetime64("2021-06-01")
RATE_DAYS = np.arange(RATE_FIRST_DAY, END_DAY)
BOOKINGS_OPEN = np.datetime64("2021-06-01T08:00:00")  # bookings for 2022 opened at 08:00 on 1 June 2021
MIGRATION = np.datetime64("2023-03-01T00:00:00")  # new booking system: lower-case channel codes, app launched
MORRA_SUNDAYS = np.datetime64("2024-06-02")  # first Sunday sailings to and from Morrowick
CASCADE = np.datetime64("2024-04-15")  # Skerry Dawn enters service on Kelva Sound
NORTH_ROUTE = np.datetime64("2024-05-01")  # Brannock Quay - Ollaby launched
SLT_CLOSURE = (np.datetime64("2023-11-06"), np.datetime64("2023-11-15"))  # Saltinish linkspan failure
MRW_WORKS = (np.datetime64("2025-02-10"), np.datetime64("2025-02-14"))  # Morrowick harbour works

MINUTE = np.timedelta64(60, "s")

# code, name, isle, district, is_mainland, has_linkspan, tidal_restricted, berths
HARBOURS = [
    ("ARD", "Ardmoor", None, "Mainland", True, True, False, 3),
    ("BRN", "Brannock Quay", None, "Mainland", True, True, False, 2),
    ("KLV", "Kelvaig", "Kelva", "Inner Isles", False, True, False, 3),
    ("SLT", "Saltinish", "Kelva", "Inner Isles", False, True, False, 1),
    ("TUL", "Tullan", "Tullan Holm", "Inner Isles", False, True, True, 1),
    ("ESK", "Eskibrae", "Eskay", "Inner Isles", False, True, False, 1),
    ("RNS", "Rennish", "Rennay", "Inner Isles", False, False, False, 1),
    ("MRW", "Morrowick", "Morra", "Inner Isles", False, True, False, 2),
    ("FEN", "Fennaby", "Fenn", "Inner Isles", False, True, True, 1),
    ("VRS", "Vorsay", "Vorsay", "Outer Isles", False, True, False, 2),
    ("OLL", "Ollaby", "Olla", "Outer Isles", False, True, False, 1),
]
CODES = [h[0] for h in HARBOURS]
HIDX = {c: i for i, c in enumerate(CODES)}
EXPOSURE = np.array([0.55, 0.6, 0.6, 0.4, 0.5, 0.6, 0.95, 0.8, 0.6, 1.0, 0.9])
LINKSPAN = np.array([h[5] for h in HARBOURS])
TIDAL = np.array([h[6] for h in HARBOURS])
# Where a sailing goes when its destination is closed by weather; a harbour not listed sends
# the vessel back to where it came from.
DIVERT_TO = {
    "KLV": "SLT",
    "SLT": "KLV",
    "ARD": "BRN",
    "BRN": "ARD",
    "VRS": "OLL",
    "OLL": "VRS",
    "MRW": "FEN",
    "FEN": "MRW",
}

# code, name, harbour a, harbour b, nautical miles, timetable minutes, turnaround minutes,
# service type, daily passengers (both directions, May), seasonality amplitude, resident share,
# freight share, weather exposure
SERVICES = [
    ("S1", "Kelva Sound", "ARD", "KLV", 18.5, 100, 35, "trunk", 1280, 1.0, 0.32, 0.05, 1.0),
    ("S2", "Morra Passage", "ARD", "MRW", 26.0, 135, 45, "lifeline", 360, 0.9, 0.45, 0.05, 1.2),
    ("S3", "North Kelva", "BRN", "KLV", 12.0, 80, 25, "trunk", 440, 0.8, 0.35, 0.04, 0.9),
    ("S4", "Tullan Shuttle", "KLV", "TUL", 3.8, 30, 10, "lifeline", 220, 0.5, 0.78, 0.015, 0.6),
    ("S5", "Eskay Link", "KLV", "ESK", 9.0, 55, 20, "lifeline", 205, 0.6, 0.62, 0.02, 0.85),
    ("S6", "Fenn Crossing", "MRW", "FEN", 6.5, 50, 15, "lifeline", 160, 0.6, 0.58, 0.015, 0.7),
    ("S7", "Isles Hopper", "ESK", "FEN", 11.0, 80, 20, "seasonal", 135, 1.0, 0.18, 0.0, 1.0),
    ("S8", "Vorsay Night Boat", "ARD", "VRS", 132.0, 540, 0, "lifeline", 220, 0.9, 0.42, 0.09, 1.3),
    ("S9", "Olla Link", "VRS", "OLL", 14.0, 95, 20, "lifeline", 130, 0.5, 0.70, 0.02, 1.1),
    ("S10", "Rennay Express", "KLV", "RNS", 22.0, 55, 15, "seasonal", 360, 1.0, 0.05, 0.0, 1.25),
    ("S11", "Saltinish Link", "SLT", "MRW", 15.5, 100, 25, "lifeline", 145, 0.6, 0.55, 0.02, 1.0),
    ("S12", "North Isles", "BRN", "OLL", 38.0, 210, 40, "seasonal", 100, 1.0, 0.15, 0.01, 1.2),
]
SVC = {s[0]: i for i, s in enumerate(SERVICES)}

# Vessel rotations: (start harbour 'a' or 'b', first departure, legs in winter, legs in summer).
# A vessel shuttles between the two harbours, so leg k leaves at first + k * (crossing + turnaround).
ROTATIONS = {
    "S1": [("a", "06:45", 8, 8), ("b", "06:30", 0, 8)],
    "S2": [("b", "07:00", 4, 6)],
    "S3": [("b", "07:00", 6, 10)],
    "S4": [("b", "06:50", 14, 18)],
    "S5": [("b", "07:15", 8, 10)],
    "S6": [("b", "07:30", 8, 10)],
    "S7": [("a", "09:00", 0, 6)],
    "S9": [("b", "07:30", 6, 8)],
    "S10": [("a", "09:00", 0, 8)],
    "S11": [("a", "07:40", 4, 6)],
    "S12": [("a", "09:00", 0, 2)],
}
SUNDAY_LEGS = {"S2": {2, 3}, "S6": {0, 1, 2, 3}, "S11": {0, 1}}  # Morra services, from MORRA_SUNDAYS

# code, name, type, built, gross tonnage, passenger certificate summer / winter, lane metres,
# crew, service speed (knots), joined fleet, left fleet
FLEET = [
    ("SL01", "Isle of Kelva", "RPX-L", 2007, 5420, 420, 300, 280, 18, 15.5, None, None),
    ("SL02", "Isle of Morra", "RPX-L", 2010, 5180, 400, 300, 260, 18, 15.0, None, None),
    ("SL03", "Skerry Dawn", "RPX-L", 2024, 6350, 480, 340, 320, 19, 16.5, "2024-03-20", None),
    ("SL04", "Vorsay Star", "RPX-N", 1999, 11800, 340, 280, 450, 28, 18.0, None, None),
    ("SL05", "Hallan Voyager", "RPX-N", 2005, 10450, 300, 260, 420, 26, 17.5, None, None),
    ("SL06", "Brannock Lass", "RPX-M", 1995, 2150, 220, 180, 110, 10, 12.0, None, "2025-10-15"),
    ("SL07", "Eskay Lass", "RPX-M", 2002, 1980, 200, 160, 90, 9, 12.0, None, None),
    ("SL08", "Tullan Belle", "RPX-S", 2014, 690, 120, 95, 36, 5, 10.0, None, None),
    ("SL09", "Fenn Bonnie", "RPX-S", 1998, 610, 110, 90, 32, 5, 9.5, None, None),
    ("SL10", "Olla Rover", "RPX-S", 2006, 760, 140, 110, 44, 6, 10.5, None, None),
    ("SL11", "Skerry Swift", "HSC", 2017, 420, 220, 150, 0, 5, 30.0, None, None),
    ("SL12", "Kelva Spirit", "RPX-M", 1988, 2480, 250, 190, 120, 11, 12.0, None, None),
    ("SL13", "Saltinish Maid", "RPX-S", 2011, 820, 150, 120, 40, 6, 11.0, None, None),
    ("SL14", "Gyre Wren", "RPX-S", 2019, 700, 130, 100, 38, 5, 10.5, None, None),
]
VIDX = {v[0]: i for i, v in enumerate(FLEET)}
CERT_SUMMER = np.array([v[5] for v in FLEET])
CERT_WINTER = np.array([v[6] for v in FLEET])
LANE_M = np.array([v[7] for v in FLEET])
SPEED = np.array([v[9] for v in FLEET])

CURRENCIES = ["EUR", "GBP", "NOK", "SEK"]
AGE_BANDS = ["0-1", "2-15", "16-25", "26-66", "67+"]
FARE_CLASSES = ["saver", "standard", "flexi", "islander"]
VEHICLE_CLASSES = ["CAR", "VAN", "MCY", "BIC", "MHM", "CVN", "HGV", "TRL", "BUS"]
CHANNELS_NEW = ["web", "app", "terminal", "phone", "agent"]
CHANNELS_OLD = ["WEB", "APP", "TERMINAL", "PHONE", "AGENT"]
HAZARDS = ["wind", "swell", "fog", "ice"]
LEVELS = [None, "yellow", "amber", "red"]
CANCEL_CODES = [None, "WX", "TEC", "CRW", "TID", "PRT"]
REFUND_REASONS = ["CXL", "SCX", "DLY", "GW"]
SEASON = np.array([0.45, 0.5, 0.65, 0.85, 1.0, 1.35, 1.75, 1.65, 1.05, 0.8, 0.55, 0.7])  # by month
WEEKDAY = np.array([0.92, 0.82, 0.85, 0.95, 1.25, 1.12, 1.09])  # Monday first
TREND = {2022: 0.9, 2023: 0.97, 2024: 1.02, 2025: 1.05}
PRICE_INDEX = {2022: 1.0, 2023: 1.06, 2024: 1.10, 2025: 1.14}


# ---------- calendar helpers ----------


def weekday(days: np.ndarray) -> np.ndarray:
    """Monday = 0 ... Sunday = 6 (1970-01-01 was a Thursday)."""
    return (days.astype("datetime64[D]").astype(np.int64) + 3) % 7


def month_of(t: np.ndarray) -> np.ndarray:
    return t.astype("datetime64[M]").astype(np.int64) % 12 + 1


def year_of(t: np.ndarray) -> np.ndarray:
    return t.astype("datetime64[Y]").astype(np.int64) + 1970


def last_sunday(year: int, month: int) -> np.datetime64:
    first_of_next = np.datetime64(f"{year + (month == 12)}-{month % 12 + 1:02d}-01")
    last = first_of_next - np.timedelta64(1, "D")
    return last - np.timedelta64(int((weekday(np.array([last]))[0] - 6) % 7), "D")


SUMMER_TIME = {
    y: (
        last_sunday(y, 3).astype("datetime64[s]") + np.timedelta64(2, "h"),
        last_sunday(y, 10).astype("datetime64[s]") + np.timedelta64(3, "h"),
    )
    for y in range(2020, 2028)
}


def utc_offset_minutes(local: np.ndarray) -> np.ndarray:
    """UTC offset in force at a local wall-clock time (no generated time falls in the
    skipped or repeated hour)."""
    years = year_of(local)
    starts = np.array([SUMMER_TIME[y][0] for y in range(2020, 2028)])
    ends = np.array([SUMMER_TIME[y][1] for y in range(2020, 2028)])
    i = years - 2020
    return np.where((local >= starts[i]) & (local < ends[i]), 120, 60).astype(np.int16)


def easter(year: int) -> np.datetime64:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return np.datetime64(f"{year}-{month:02d}-{day:02d}")


def hhmm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def grouped_cumsum(values: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Cumulative sum within runs of equal `groups` (rows must be sorted by group)."""
    total = np.cumsum(values)
    starts = np.r_[True, groups[1:] != groups[:-1]]
    before = np.where(starts, total - values, 0)
    return total - np.maximum.accumulate(before)


def categorical(rng: np.random.Generator, probs, k: int) -> np.ndarray:
    """k draws from one categorical distribution (probabilities need not sum to 1)."""
    cum = np.cumsum(np.asarray(probs, dtype=float))
    return np.searchsorted(cum / cum[-1], rng.random(k), side="right")


def by_group(rng: np.random.Generator, n: int, groups: list, default: int = 0) -> np.ndarray:
    """A categorical draw per row, from the distribution of the first group (mask, probs) it is in."""
    out = np.full(n, default, dtype=np.int64)
    free = np.ones(n, dtype=bool)
    for mask, probs in groups:
        idx = np.flatnonzero(mask & free)
        out[idx] = categorical(rng, probs, len(idx))
        free[idx] = False
    return out


def skip_gap(t: np.ndarray) -> np.ndarray:
    """Moves local times that fall in the hour skipped when summer time starts one hour on."""
    out = t.copy()
    for start, _ in SUMMER_TIME.values():
        gap = (out >= start) & (out < start + np.timedelta64(1, "h"))
        out = np.where(gap, out + np.timedelta64(1, "h"), out)
    return out


# ---------- timetable and fleet deployment ----------


def refit_windows() -> list[tuple[str, np.datetime64, np.datetime64, str | None]]:
    """Annual dry-dock periods, inclusive, with the relief vessel that covers each one."""
    out = []
    for year in (2022, 2023, 2024, 2025):
        shift = 2 * (year - 2022)

        def window(
            vessel: str, month: int, day: int, length: int, relief: str | None, y: int = year, s: int = shift
        ) -> None:
            start = np.datetime64(f"{y}-{month:02d}-{day:02d}") + np.timedelta64(s, "D")
            out.append((vessel, start, start + np.timedelta64(length - 1, "D"), relief))

        relief_major = "SL06" if year == 2025 else "SL12"
        window("SL02", 1, 10, 21, relief_major)
        window("SL01", 2, 1, 21, "SL12")
        window("SL07", 2, 23, 14, relief_major)
        if year <= 2024:
            window("SL06", 3, 10, 15, "SL12")
        else:
            window("SL03", 3, 10, 15, "SL12")
            window("SL06", 4, 1, 14, None)
        window("SL04", 1, 16, 22, "SL05")
        window("SL08", 1, 12, 14, "SL14")
        window("SL09", 1, 27, 14, "SL14")
        window("SL10", 2, 11, 14, "SL14")
        window("SL13", 2, 26, 14, "SL14")
        window("SL11", 4, 6, 20, None)
        window("SL05", 3, 6, 18, None)
        window("SL12", 11, 2, 18, None)
        window("SL14", 10, 6, 12, None)
    return out


def rostered_vessel(service: str, slot: int, day: np.datetime64) -> str:
    if service == "S1":
        return ("SL01" if day < CASCADE else "SL03") if slot == 0 else "SL12"
    if service == "S3":
        return "SL06" if day < CASCADE else "SL01"
    return {
        "S2": "SL02",
        "S4": "SL08",
        "S5": "SL07",
        "S6": "SL09",
        "S7": "SL14",
        "S9": "SL10",
        "S10": "SL11",
        "S11": "SL13",
        "S12": "SL06",
    }[service]


def timetable() -> dict[str, np.ndarray]:
    """Every scheduled leg: service, direction, local times and the vessel that works it."""
    relief = {}
    for vessel, start, end, cover in refit_windows():
        for day in np.arange(start, end + np.timedelta64(1, "D")):
            if cover:
                relief[(vessel, day)] = cover
    rows = []  # service index, from harbour, to harbour, departure, arrival, vessel
    for day in DAYS:
        month = int(month_of(np.array([day]))[0])
        dow = int(weekday(np.array([day]))[0])
        md = (month, int(str(day)[8:10]))
        summer = 5 <= month <= 9
        day_number = int((day - FIRST_DAY).astype(np.int64))
        midnight = day.astype("datetime64[m]")
        legs = []  # (service, slot, leg, from, to, dep minute, arrival as minutes after midnight)
        for code, _, a, b, _, minutes, turn, *_ in SERVICES:
            if code == "S8":
                if summer or dow in (0, 2, 4):
                    legs.append(
                        (
                            code,
                            0 if (not summer or day_number % 2 == 0) else 1,
                            0,
                            a,
                            b,
                            hhmm("22:30"),
                            1440 + hhmm("07:30"),
                        )
                    )
                if summer or dow in (1, 3, 5):
                    legs.append(
                        (
                            code,
                            0 if (not summer or day_number % 2 == 1) else 1,
                            1,
                            b,
                            a,
                            hhmm("21:00"),
                            1440 + hhmm("06:00"),
                        )
                    )
                continue
            if code == "S7" and not summer:
                continue
            if code == "S10" and not ((5, 15) <= md <= (9, 15)):
                continue
            if code == "S12" and not (day >= NORTH_ROUTE and summer and dow >= 3):
                continue
            for slot, (start, first, n_winter, n_summer) in enumerate(ROTATIONS[code]):
                n = n_summer if summer else n_winter
                t = hhmm(first)
                at_a = start == "a"
                for k in range(n):
                    if code == "S4" and k == 8:
                        t += 60  # crew break
                    keep = True
                    if code in SUNDAY_LEGS and dow == 6:
                        keep = day >= MORRA_SUNDAYS and k in SUNDAY_LEGS[code]
                    if keep:
                        legs.append((code, slot, k, a if at_a else b, b if at_a else a, t, t + minutes))
                    t += minutes + turn
                    at_a = not at_a
        if md == (12, 25):
            legs = []
        elif md in ((12, 26), (1, 1)):
            legs = [g for g in legs if g[5] >= 720]
        elif md in ((12, 24), (12, 31)):
            legs = [g for g in legs if g[5] < 1080]
        for code, slot, k, frm, to, dep, arr in legs:
            vessel = rostered_vessel(code, slot, day) if code != "S8" else ("SL04" if slot == 0 else "SL05")
            vessel = relief.get((vessel, day), vessel)
            dep_at, arr_at = midnight + np.timedelta64(dep, "m"), midnight + np.timedelta64(arr, "m")
            rows.append((SVC[code], HIDX[frm], HIDX[to], dep_at, arr_at, VIDX[vessel]))
    cols = list(zip(*rows))
    return {
        "service": np.array(cols[0], dtype=np.int16),
        "frm": np.array(cols[1], dtype=np.int16),
        "to": np.array(cols[2], dtype=np.int16),
        "std": np.array(cols[3], dtype="datetime64[m]").astype("datetime64[s]"),
        "sta": np.array(cols[4], dtype="datetime64[m]").astype("datetime64[s]"),
        "vessel": np.array(cols[5], dtype=np.int16),
    }


# ---------- weather ----------


def weather(rng: np.random.Generator) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    """Met warnings, plus the day's worst wind or swell level and fog flag per harbour."""
    n_days, n_ports = len(DAYS), len(CODES)
    months = month_of(DAYS)
    storm_chance = np.array([0.24, 0.21, 0.15, 0.08, 0.04, 0.025, 0.02, 0.03, 0.08, 0.16, 0.22, 0.25])
    intensity = np.zeros((n_days, n_ports))
    for d in range(n_days):
        if rng.random() < storm_chance[months[d] - 1]:
            peak = 0.3 + 0.7 * rng.random() ** 1.6
            length = 1 + int(rng.random() < 0.45) + int(rng.random() < 0.2)
            for k in range(length):
                if d + k < n_days:
                    hit = peak * (1.0, 0.7, 0.45)[k] * EXPOSURE * (0.7 + 0.4 * rng.random(n_ports))
                    intensity[d + k] = np.maximum(intensity[d + k], hit)
    wind = (intensity >= 0.28).astype(np.int8) + (intensity >= 0.48) + (intensity >= 0.68)
    rows = []  # day, port, hazard, level, gust
    for d in range(n_days):
        for p in range(n_ports):
            if wind[d, p]:
                lvl = int(wind[d, p])
                gust = int((34, 45, 55)[lvl - 1] + rng.integers(0, (11, 10, 18)[lvl - 1]))
                rows.append((d, p, 0, lvl, gust))
                if EXPOSURE[p] >= 0.8 and lvl >= 2 and rng.random() < 0.6:
                    rows.append((d, p, 1, lvl - 1, -1))
        fog_chance = 0.05 if 5 <= months[d] <= 9 else 0.015
        if rng.random() < fog_chance:
            for p in rng.choice(n_ports, size=int(rng.integers(1, 5)), replace=False):
                rows.append((d, int(p), 2, 1 if rng.random() < 0.8 else 2, -1))
        if months[d] in (1, 2) and rng.random() < 0.03:
            for p in (HIDX["TUL"], HIDX["ESK"], HIDX["FEN"]):
                rows.append((d, p, 3, 1, -1))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    day_i = np.array([r[0] for r in rows])
    port = np.array([r[1] for r in rows])
    hazard = np.array([r[2] for r in rows])
    level = np.array([r[3] for r in rows])
    gust = np.array([r[4] for r in rows])
    n = len(rows)
    evening_before = rng.random(n) < 0.72
    issue_minute = np.where(evening_before, -1440 + 900 + rng.integers(0, 420, n), 240 + rng.integers(0, 240, n))
    issued = (
        DAYS[day_i].astype("datetime64[s]") + issue_minute * MINUTE + rng.integers(0, 60, n) * np.timedelta64(1, "s")
    )
    # Updates re-issue a warning for the same harbour, day and hazard at a new level.
    again = rng.random(n) < 0.09
    up = rng.random(n) < 0.7
    new_level = np.where(up, np.minimum(level + 1, 3), np.maximum(level - 1, 1))
    new_level = np.where(new_level == level, np.where(level == 3, 2, level + 1), new_level)
    new_level = np.where(hazard >= 2, np.minimum(new_level, 2), new_level)  # fog and ice top out at amber
    later = issued + (120 + rng.integers(0, 420, n)) * MINUTE
    new_gust = np.where(hazard == 0, np.array([34, 45, 55])[new_level - 1] + rng.integers(0, 10, n), -1)
    sel = np.flatnonzero(again)
    warnings = {
        "day": np.r_[day_i, day_i[sel]],
        "port": np.r_[port, port[sel]],
        "hazard": np.r_[hazard, hazard[sel]],
        "level": np.r_[level, new_level[sel]],
        "gust": np.r_[gust, new_gust[sel]],
        "issued": np.r_[issued, later[sel]],
    }
    worst = np.zeros((n_days, n_ports), dtype=np.int8)
    fog = np.zeros((n_days, n_ports), dtype=bool)
    windy = np.isin(warnings["hazard"], (0, 1))
    np.maximum.at(worst, (warnings["day"][windy], warnings["port"][windy]), warnings["level"][windy].astype(np.int8))
    fog[warnings["day"][warnings["hazard"] == 2], warnings["port"][warnings["hazard"] == 2]] = True
    return warnings, worst, fog


# ---------- what happened to each sailing ----------


def breakdowns(rng: np.random.Generator) -> list[tuple[int, np.datetime64, np.datetime64]]:
    out = []
    for v in range(len(FLEET)):
        for year in (2022, 2023, 2024, 2025):
            for _ in range(int(rng.poisson(1.0))):
                day = np.datetime64(f"{year}-01-01") + np.timedelta64(int(rng.integers(0, 365)), "D")
                start = day.astype("datetime64[s]") + np.timedelta64(int(rng.integers(6 * 60, 20 * 60)), "m")
                days = 1 + int(rng.random() < 0.5) + int(rng.random() < 0.2)
                out.append((v, start, (day + np.timedelta64(days, "D")).astype("datetime64[s]")))
    return out


def sailing_outcomes(
    tt: dict[str, np.ndarray], worst: np.ndarray, fog: np.ndarray, rng: np.random.Generator
) -> dict[str, np.ndarray]:
    n = len(tt["std"])
    svc = tt["service"]
    day_i = (tt["std"].astype("datetime64[D]") - FIRST_DAY).astype(np.int64)
    days = tt["std"].astype("datetime64[D]")
    months = month_of(days)
    years = year_of(days)
    exposure = np.array([s[12] for s in SERVICES])[svc]
    minutes = np.array([s[5] for s in SERVICES])[svc]
    nm = np.array([s[4] for s in SERVICES])[svc]
    lvl_dep = worst[day_i, tt["frm"]]
    lvl_dst = worst[day_i, tt["to"]]
    lvl = np.maximum(lvl_dep, lvl_dst)
    dep_hour = (tt["std"] - days.astype("datetime64[s]")).astype(np.int64) / 3600.0

    # Weather closes a service for a window of hours on amber and red days.
    key = svc.astype(np.int64) * 10_000 + day_i
    uniq, inverse = np.unique(key, return_inverse=True)
    day_lvl = np.zeros(len(uniq), dtype=np.int8)
    np.maximum.at(day_lvl, inverse, lvl)
    w_start = np.where(day_lvl == 3, 4 + 7 * rng.random(len(uniq)), 5 + 11 * rng.random(len(uniq)))
    w_len = np.where(day_lvl == 3, 9 + 9 * rng.random(len(uniq)), 4 + 6 * rng.random(len(uniq)))
    in_window = (dep_hour >= w_start[inverse]) & (dep_hour < w_start[inverse] + w_len[inverse])
    p_wx = np.select(
        [lvl == 3, lvl == 2, lvl == 1],
        [
            np.where(in_window, np.minimum(0.98, 0.85 * exposure), 0.15),
            np.where(in_window, np.minimum(0.95, 0.55 * exposure), 0.04),
            0.015 * exposure,
        ],
        0.0,
    )
    code = np.zeros(n, dtype=np.int8)  # index into CANCEL_CODES
    code[rng.random(n) < np.where((years == 2022) & (months >= 6) & (months <= 8), 0.012, 0.001)] = 3
    spring = ((day_i + 4.3) % 14.765) < 1.8
    tidal = (TIDAL[tt["frm"]] | TIDAL[tt["to"]]) & spring
    code[tidal & (rng.random(n) < 0.04)] = 4
    code[rng.random(n) < p_wx] = 1
    code[rng.random(n) < 0.0012] = 2
    for v, start, end in breakdowns(rng):
        code[(tt["vessel"] == v) & (tt["std"] >= start) & (tt["std"] < end)] = 2
    touches = lambda h: (tt["frm"] == HIDX[h]) | (tt["to"] == HIDX[h])  # noqa: E731
    code[touches("SLT") & (days >= SLT_CLOSURE[0]) & (days < SLT_CLOSURE[1])] = 5
    code[touches("MRW") & (days >= MRW_WORKS[0]) & (days < MRW_WORKS[1])] = 5

    divert = (
        (code == 0) & (lvl_dst >= 2) & (rng.random(n) < np.minimum(0.8, np.where(lvl_dst == 3, 0.6, 0.3) * exposure))
    )
    to_codes = np.array(CODES)[tt["to"]]
    alt = np.array([HIDX.get(DIVERT_TO.get(c, ""), -1) for c in to_codes])
    alt = np.where((alt < 0) | (alt == tt["frm"]), tt["frm"], alt)

    # Departure delay before knock-on effects, in seconds.
    u = rng.random(n)
    r = rng.random(n)
    own = np.select(
        [u < 0.06, u < 0.86, u < 0.95, u < 0.985, u < 0.995],
        [-(60 + 180 * r), 300 * r**1.5, 300 + 600 * r, 900 + 1800 * r, 2700 + 2700 * r],
        5400 + 9000 * r,
    )
    wx_delay = rng.random(n)
    own += np.where((lvl_dep == 2) & (wx_delay < 0.25), 600 + 2400 * rng.random(n), 0)
    own += np.where((lvl_dep == 3) & (wx_delay < 0.5), 1200 + 6000 * rng.random(n), 0)
    own += np.where(fog[day_i, tt["frm"]] & (rng.random(n) < 0.5), 300 + 1500 * rng.random(n), 0)
    busy = np.isin(svc, [SVC["S1"], SVC["S2"], SVC["S3"], SVC["S8"]]) & (months >= 7) & (months <= 8)
    own += np.where(busy & (rng.random(n) < 0.5), 480 * rng.random(n), 0)
    own = np.round(own)

    std_off = utc_offset_minutes(tt["std"])
    sta_off = utc_offset_minutes(tt["sta"])
    std_utc = tt["std"] - std_off.astype(np.int64) * MINUTE
    sta_utc = tt["sta"] - sta_off.astype(np.int64) * MINUTE
    sea = nm / SPEED[tt["vessel"]] * 60 + np.where(minutes <= 60, 5, 12)
    factor_a = rng.random(n)
    factor_b = rng.random(n)
    weather_factor = np.select([lvl == 3, lvl == 2], [1.12, 1.06], 1.0)
    duration = np.maximum(sea * (1.0 + 0.04 * factor_a), minutes * (0.92 + 0.08 * factor_b)) * weather_factor
    duration = np.where(divert & (alt != tt["frm"]), duration * (1.15 + 0.45 * rng.random(n)), duration)
    turn_back = divert & (alt == tt["frm"])
    duration = np.where(turn_back, 40 + 80 * rng.random(n), duration)
    night_target = (rng.random(n) * 25 - 15) * 60  # S8 aims at its timetable arrival, -15 to +10 minutes
    reposition = 40 + 70 * rng.random(n)
    min_turn = np.where(minutes <= 60, 360, 600)  # seconds alongside before the next departure

    # Walk each vessel's day in order: a vessel that did not reach a harbour cannot sail from it,
    # a late arrival delays the next departure, and a diversion costs time to reposition.
    atd = np.full(n, np.datetime64("NaT"), dtype="datetime64[s]")
    ata = np.full(n, np.datetime64("NaT"), dtype="datetime64[s]")
    arrived = np.full(n, -1, dtype=np.int16)
    order = np.lexsort((std_utc, tt["vessel"]))
    vday = tt["vessel"].astype(np.int64) * 100_000 + day_i
    s8 = SVC["S8"]
    prev_v = -1
    pos = -1
    prev_ata = None
    displaced_by = 1
    extra = 0.0
    for i in order:
        if vday[i] != prev_v:
            prev_v, pos, prev_ata, extra, displaced_by = vday[i], int(tt["frm"][i]), None, 0.0, 1
        if code[i] == 0 and int(tt["frm"][i]) != pos:
            code[i] = displaced_by
        if code[i]:
            displaced_by = int(code[i])
            continue
        dep = std_utc[i] + np.timedelta64(int(own[i] + extra * 60), "s")
        extra = 0.0
        if prev_ata is not None:
            dep = max(dep, prev_ata + np.timedelta64(int(min_turn[i]), "s"))
        if svc[i] == s8:
            target = sta_utc[i] + np.timedelta64(int(night_target[i]), "s")
            dur = max(sea[i] * 60, (target - dep).astype(np.int64))
        else:
            dur = duration[i] * 60
        atd[i] = dep
        ata[i] = dep + np.timedelta64(int(round(dur)), "s")
        prev_ata = ata[i]
        if divert[i]:
            arrived[i] = alt[i]
            if alt[i] == tt["frm"][i]:
                pos = int(tt["frm"][i])
                displaced_by = 1
            else:
                pos = int(tt["to"][i])
                extra = reposition[i]
        else:
            arrived[i] = tt["to"][i]
            pos = int(tt["to"][i])
    status = np.where(code > 0, 2, np.where(divert, 1, 0))  # sailed, diverted, cancelled
    unrecorded = (code > 0) & (rng.random(n) < np.where(years == 2022, 0.08, 0.03))
    code_out = np.where(unrecorded, 0, code)
    return {
        "std_off": std_off,
        "sta_off": sta_off,
        "std_utc": std_utc,
        "atd": atd,
        "ata": ata,
        "status": status,
        "arrived": arrived,
        "cancel": code_out,
        "lvl": lvl,
    }


# ---------- bookings ----------


def demand(tt: dict[str, np.ndarray], out: dict[str, np.ndarray], rng: np.random.Generator) -> np.ndarray:
    """Expected passengers per sailing."""
    n = len(tt["std"])
    svc = tt["service"]
    days = tt["std"].astype("datetime64[D]")
    day_i = (days - FIRST_DAY).astype(np.int64)
    months = month_of(days)
    dows = weekday(days)
    years = year_of(days)
    hours = (tt["std"] - days.astype("datetime64[s]")).astype(np.int64) // 3600
    amp = np.array([s[9] for s in SERVICES])[svc]
    daily = np.array([s[8] for s in SERVICES], dtype=float)[svc]
    season = 1 + amp * (SEASON[months - 1] - 1)
    trend = np.vectorize(TREND.get)(years)
    md = months * 100 + (days - days.astype("datetime64[M]").astype("datetime64[D]")).astype(np.int64) + 1
    holiday = np.select([(md >= 1220) & (md <= 1223), (md >= 1226) & (md <= 1230)], [1.3, 1.15], 1.0)
    for y in (2022, 2023, 2024, 2025):
        e = easter(y)
        holiday = np.where((days >= e - np.timedelta64(6, "D")) & (days <= e + np.timedelta64(1, "D")), 1.2, holiday)
    key = svc.astype(np.int64) * 10_000 + day_i
    uniq, inverse = np.unique(key, return_inverse=True)
    day_noise = (0.85 + 0.3 * rng.random(len(uniq)))[inverse]
    tod = np.select(
        [hours < 7, hours < 9, hours < 13, hours < 17, hours < 20, hours < 22],
        [0.75, 1.05, 1.25, 1.15, 0.95, 0.65],
        0.5,
    )
    tod = np.where(svc == SVC["S8"], 1.0, tod)
    from_klv = tt["frm"] == HIDX["KLV"]
    s10 = svc == SVC["S10"]
    tod = np.where(s10 & from_klv, np.where(hours < 12, 1.6, 0.6), np.where(s10, np.where(hours < 12, 0.5, 1.6), tod))
    weight_sum = np.zeros(len(uniq))
    np.add.at(weight_sum, inverse, tod)
    mainland = (tt["frm"] == HIDX["ARD"]) | (tt["frm"] == HIDX["BRN"])
    to_mainland = (tt["to"] == HIDX["ARD"]) | (tt["to"] == HIDX["BRN"])
    direction = np.where((dows == 4) & mainland & (hours >= 14), 1.3, 1.0) * np.where(
        (dows == 6) & to_mainland & (hours >= 13), 1.3, 1.0
    )
    weather_mult = np.select([out["lvl"] == 3, out["lvl"] == 2], [0.55, 0.85], 1.0)
    leg_noise = 0.5 + rng.random((n, 4)).mean(axis=1)
    return (
        daily
        * season
        * WEEKDAY[dows]
        * trend
        * holiday
        * day_noise
        * tod
        / weight_sum[inverse]
        * direction
        * weather_mult
        * leg_noise
    )


def filled_rates(rates: dict[str, np.ndarray]) -> np.ndarray:
    """EUR per unit for every currency (EUR first) on every day of RATE_DAYS: the latest
    published rate on or before that day."""
    table = np.ones((len(CURRENCIES), len(RATE_DAYS)))
    for c in range(1, len(CURRENCIES)):
        sel = rates["currency"] == c
        idx = (rates["day"][sel] - RATE_FIRST_DAY).astype(np.int64)
        values = np.full(len(RATE_DAYS), np.nan)
        values[idx] = rates["rate"][sel]
        last = np.maximum.accumulate(np.where(np.isnan(values), -1, np.arange(len(RATE_DAYS))))
        table[c] = values[last]
    return table


def bookings(
    tt: dict[str, np.ndarray], out: dict[str, np.ndarray], fx: np.ndarray, rng: np.random.Generator
) -> dict[str, dict[str, np.ndarray]]:
    expected = demand(tt, out, rng)
    svc = tt["service"]
    days = tt["std"].astype("datetime64[D]")
    months = month_of(days)
    dows = weekday(days)
    years = year_of(days)
    summer = (months >= 5) & (months <= 9)
    peak = (months >= 6) & (months <= 8)
    vessel = tt["vessel"]
    cert_season = (months >= 4) & (months <= 10)
    cert = np.where(cert_season, CERT_SUMMER[vessel], CERT_WINTER[vessel])
    deck = (LANE_M[vessel] > 0) & LINKSPAN[tt["frm"]] & LINKSPAN[tt["to"]]
    resident_season = np.array([1.35, 1.35, 1.2, 1.05, 1.0, 0.85, 0.6, 0.6, 0.95, 1.1, 1.3, 1.2])[months - 1]
    r_share = np.minimum(0.95, np.array([s[10] for s in SERVICES])[svc] * resident_season)
    f_share = np.array([s[11] for s in SERVICES])[svc] * np.where(dows < 5, 1.25, np.where(dows == 5, 0.6, 0.3)) * deck
    party = f_share * 0.78 + (1 - f_share) * (r_share * 1.58 + (1 - r_share) * 2.48)
    n_book = rng.poisson(expected / party)

    sid = np.repeat(np.arange(len(svc)), n_book)
    n = len(sid)
    u = rng.random(n)
    seg = np.where(u < f_share[sid], 2, np.where(u < f_share[sid] + (1 - f_share[sid]) * r_share[sid], 0, 1))
    s_summer, s_peak = summer[sid], peak[sid]
    # Party types: 0 resident solo, 1 resident pair, 2 resident family, 3 visitor solo, 4 couple,
    # 5 visitor family, 6 group, 7 freight driver, 8 unaccompanied trailer.
    ptype = by_group(
        rng,
        n,
        [
            (seg == 0, [0.68, 0.18, 0.14]),
            ((seg == 1) & ~s_peak, [0, 0, 0, 0.27, 0.40, 0.25, 0.08]),
            ((seg == 1) & s_peak, [0, 0, 0, 0.23, 0.36, 0.33, 0.08]),
            (seg == 2, [0, 0, 0, 0, 0, 0, 0, 0.78, 0.22]),
        ],
    )
    kids = 1 + (rng.random(n) < 0.5).astype(np.int64) + (rng.random(n) < 0.2)
    infant = rng.random(n) < 0.18
    family = (ptype == 2) | (ptype == 5)
    size = np.select(
        [np.isin(ptype, (0, 3, 7)), np.isin(ptype, (1, 4)), family, ptype == 6],
        [1, 2, 2 + kids + infant, 4 + rng.integers(0, 4, n)],
        0,
    )

    # Vehicles: one motor vehicle at most, a caravan behind some cars, and bicycles.
    # Classes: 0 CAR 1 VAN 2 MCY 3 BIC 4 MHM 5 CVN 6 HGV 7 TRL 8 BUS, 9 none.
    vp = {
        0: {0: 0.38, 1: 0.12},
        1: {0: 0.55},
        2: {0: 0.65},
        3: {0: 0.22, 2: 0.03, 4: 0.02},
        4: {0: 0.38, 2: 0.02, 4: 0.035},
        5: {0: 0.62, 4: 0.05},
        6: {0: 0.03, 8: 0.15},
        7: {6: 1.0},
        8: {7: 1.0},
    }
    bus_ok = np.isin(svc[sid], [SVC["S1"], SVC["S2"], SVC["S3"], SVC["S8"]])
    groups = []
    for t, cls in vp.items():
        for in_summer in (False, True):
            for coach in (False, True):
                probs = np.zeros(10)
                for c, p in cls.items():
                    probs[c] = p * (2.0 if c in (2, 4) and in_summer else 1.0) * (coach if c == 8 else 1.0)
                probs[9] = max(0.0, 1.0 - probs[:9].sum())
                groups.append(((ptype == t) & (s_summer == in_summer) & (bus_ok == coach), probs))
    motor = by_group(rng, n, groups, default=9)
    motor = np.where(deck[sid], motor, 9)
    caravan = (motor == 0) & (seg == 1) & (rng.random(n) < np.where(s_summer, 0.06, 0.03))
    p_bike = np.where(seg == 1, np.where(s_summer, 0.10, 0.02), np.where(seg == 0, 0.02, 0.0))
    p_bike = np.where(svc[sid] == SVC["S10"], np.where(s_summer, 0.08, 0.0), p_bike)
    bikes = np.where(motor == 9, rng.binomial(size, p_bike), 0)

    # Channel (0 web, 1 terminal, 2 phone, 3 agent), lead time and booked_at (local time).
    chan = by_group(
        rng,
        n,
        [(seg == 0, [0.48, 0.38, 0.14, 0.0]), (seg == 1, [0.64, 0.12, 0.06, 0.18]), (seg == 2, [0.65, 0.0, 0.35, 0.0])],
    )
    terminal = chan == 1
    std = tt["std"][sid]
    a, b = rng.random(n), rng.random(n)
    lead_days = np.select(
        [chan == 3, chan == 2, (chan == 0) & (seg == 0), (chan == 0) & (seg == 1)],
        [
            30 + 270 * a,
            np.where(b < 0.4, 3 * a, np.where(b < 0.8, 3 + 27 * a, 30 + 90 * a)),
            np.where(b < 0.4, 2 * a, np.where(b < 0.7, 2 + 12 * a, 14 + 76 * a)),
            np.where(b < 0.15, 7 * a, np.where(b < 0.55, 7 + 53 * a, 60 + 180 * a)),
        ],
        0.2 + 5.8 * a,
    )
    web_hours = [
        0.6,
        0.3,
        0.0,
        0.1,
        0.1,
        0.2,
        0.6,
        1.2,
        1.8,
        2.2,
        2.4,
        2.4,
        2.3,
        2.3,
        2.4,
        2.4,
        2.5,
        2.6,
        2.8,
        3.2,
        3.4,
        3.0,
        2.2,
        1.3,
    ]
    office = lambda first, last: [1.0 if first <= h <= last else 0.0 for h in range(24)]  # noqa: E731
    hour = by_group(
        rng, n, [(chan == 2, office(8, 20)), (chan == 3, office(8, 17)), (np.ones(n, dtype=bool), web_hours)]
    )
    second = np.timedelta64(1, "s")
    booked_day = (std - (lead_days * 86400).astype(np.int64) * second).astype("datetime64[D]")
    booked = booked_day.astype("datetime64[s]") + (hour * 3600 + rng.integers(0, 3600, n)) * second
    too_late = booked > std - 20 * MINUTE
    booked = np.where(too_late, std - (20 + rng.integers(0, 280, n)) * MINUTE, booked)
    # Phone and agent bookings are made in office hours, so a late one moves to the day before.
    office_day = (std.astype("datetime64[D]") - np.timedelta64(1, "D")).astype("datetime64[s]")
    office_late = too_late & ((chan == 2) | (chan == 3))
    booked = np.where(office_late, office_day + (9 * 3600 + rng.integers(0, 8 * 3600, n)) * second, booked)
    day_start = std.astype("datetime64[D]").astype("datetime64[s]") + 330 * MINUTE
    window = np.maximum(5, np.minimum(180, (std - day_start).astype(np.int64) // 60))
    booked = np.where(terminal, std - (5 + (rng.random(n) * (window - 5)).astype(np.int64)) * MINUTE, booked)
    onboard = terminal & (out["status"][sid] != 2) & (rng.random(n) < 0.015)
    booked = np.where(onboard, std + (2 + rng.integers(0, 39, n)) * MINUTE, booked)
    whole_minutes = (too_late & ~office_late) | terminal
    booked = booked + np.where(whole_minutes, rng.integers(0, 60, n), 0) * second
    early = booked < BOOKINGS_OPEN
    booked = np.where(early, BOOKINGS_OPEN + rng.integers(0, 15 * 3600, n) * second, booked)
    booked = skip_gap(booked)

    # Sold out: drop vehicle bookings beyond the lane metres, then bookings beyond the
    # passenger certificate, in the order they were made.
    car_len, cvn_len = vehicle_lengths(rng, motor, caravan)
    lane = np.where(motor < 9, car_len, 0) + np.where(caravan, cvn_len, 0)
    order = np.lexsort((booked, sid))
    keep = np.ones(n, dtype=bool)
    lane_cum = grouped_cumsum(lane[order], sid[order])
    keep[order] = ~((lane[order] > 0) & (lane_cum > LANE_M[vessel][sid[order]]))
    pax = np.where(keep, size, 0)
    pax_cum = grouped_cumsum(pax[order], sid[order])
    keep[order] &= pax_cum <= cert[sid[order]]
    k = np.flatnonzero(keep)
    k = k[np.lexsort((k, booked[k]))]  # final order: booked_at, then generation order
    sid, seg, ptype, size, kids, infant, motor, caravan, bikes, chan, terminal, booked, onboard, car_len, cvn_len = (
        x[k]
        for x in (
            sid,
            seg,
            ptype,
            size,
            kids,
            infant,
            motor,
            caravan,
            bikes,
            chan,
            terminal,
            booked,
            onboard,
            car_len,
            cvn_len,
        )
    )
    n = len(sid)
    std = tt["std"][sid]
    s_summer, s_peak = summer[sid], peak[sid]

    # Passengers: age band (0 '0-1', 1 '2-15', 2 '16-25', 3 '26-66', 4 '67+'), fare class
    # (0 saver, 1 standard, 2 flexi, 3 islander) and residence.
    p_book = np.repeat(np.arange(n), size)
    p_seq = np.arange(len(p_book)) - np.repeat(np.cumsum(size) - size, size)
    pt = ptype[p_book]
    m = len(p_book)
    school = np.isin(svc[sid][p_book], [SVC["S4"], SVC["S5"], SVC["S6"], SVC["S9"], SVC["S11"]]) & (
        dows[sid][p_book] < 5
    )
    band = by_group(
        rng,
        m,
        [
            ((pt == 0) & school, [0, 0.3, 0.12, 0.63, 0.20]),
            (pt == 0, [0, 0.05, 0.12, 0.63, 0.20]),
            (pt == 1, [0, 0, 0.1, 0.6, 0.3]),
            (pt == 3, [0, 0, 0.25, 0.6, 0.15]),
            (pt == 6, [0, 0, 0.3, 0.4, 0.3]),
        ],
        default=3,
    )
    couple_band = categorical(rng, [0, 0, 0.15, 0.6, 0.25], n)
    band = np.where(pt == 4, couple_band[p_book], band)
    fam = (pt == 2) | (pt == 5)
    band = np.where(fam & (p_seq >= 2), np.where(p_seq < 2 + kids[p_book], 1, 0), band)
    guest = np.isin(ptype, (1, 2)) & (rng.random(n) < 0.08)
    driver_resident = rng.random(n) < 0.3
    resident = np.select(
        [seg[p_book] == 0, seg[p_book] == 2], [~(guest[p_book] & (p_seq == 1)), driver_resident[p_book]], False
    )
    res_class = categorical(rng, [0, 0.08, 0.04, 0.88], n)
    vis_class = categorical(rng, [0.38, 0.45, 0.17], n)
    fclass = np.select(
        [seg[p_book] == 0, seg[p_book] == 1], [np.where(resident, res_class[p_book], 1), vis_class[p_book]], 1
    )
    fclass = np.where((seg[p_book] == 1) & (rng.random(m) < 0.0015), 3, fclass)
    # Refund rules follow the most flexible ticket in the booking (0 saver, 1 standard, 2 flexi).
    has_flexi = np.bincount(p_book, weights=fclass == 2, minlength=n) > 0
    has_std = np.bincount(p_book, weights=(fclass == 1) | (fclass == 3), minlength=n) > 0
    rclass = np.where(has_flexi, 2, np.where(has_std | (size == 0), 1, 0))

    # Vehicle rows: motor vehicle, then caravan, then bicycles.
    n_veh = (motor < 9).astype(np.int64) + caravan + bikes
    v_book = np.repeat(np.arange(n), n_veh)
    v_seq = np.arange(len(v_book)) - np.repeat(np.cumsum(n_veh) - n_veh, n_veh) + 1
    has_motor = (motor < 9)[v_book]
    v_class = np.where(
        has_motor & (v_seq == 1), motor[v_book], np.where(caravan[v_book] & (v_seq == 1 + has_motor), 5, 3)
    )
    bike_len = np.round(1.7 + 0.2 * rng.random(len(v_book)), 2)
    v_len = np.where(v_class == 5, cvn_len[v_book], np.where(has_motor & (v_seq == 1), car_len[v_book], bike_len))

    # Fares in EUR.
    s_nm = np.array([s[4] for s in SERVICES])[svc]
    price = np.vectorize(PRICE_INDEX.get)(years)
    pax_base = (3.0 + 0.30 * s_nm) * np.where(svc == SVC["S10"], 1.4, 1.0) * price
    age_f = np.array([0.0, 0.5, 0.75, 1.0, 0.6])[band]
    class_f = np.array([0.8, 1.0, 1.3, 0.35])[fclass]
    surcharge = np.where(s_peak[p_book] & (fclass != 3), 1.15, 1.0)
    p_fare = pax_base[sid][p_book] * age_f * class_f * surcharge
    per_m = (1.2 + 0.11 * s_nm) * price
    v_factor = np.array([1.0, 1.0, 0.7, 0.0, 1.0, 1.0, 1.25, 1.25, 1.25])[v_class]
    res_disc = np.where((seg[v_book] == 0) & np.isin(v_class, (0, 1, 2, 5)), 0.5, 1.0)
    v_fare = np.where(v_class == 3, 2.5 * price[sid][v_book], per_m[sid][v_book] * v_len * v_factor * res_disc)
    cabin = (svc[sid] == SVC["S8"]) & (seg != 2) & (rng.random(n) < 0.45)
    cabin_fare = np.where(cabin, np.where(size <= 2, 65.0, 98.0) * price[sid], 0.0)
    fare_eur = np.round(
        np.bincount(p_book, weights=p_fare, minlength=n)
        + np.bincount(v_book, weights=v_fare, minlength=n)
        + cabin_fare,
        2,
    )

    # Currency (0 EUR, 1 GBP, 2 NOK, 3 SEK), at the rate in force on the booking date.
    cur = by_group(rng, n, [((seg == 1) & (chan == 3), [0.10, 0.25, 0.35, 0.30]), (seg == 1, [0.55, 0.20, 0.15, 0.10])])
    rate = fx[cur, (booked.astype("datetime64[D]") - RATE_FIRST_DAY).astype(np.int64)]
    amount = np.where(cur >= 2, np.round(fare_eur / rate), np.round(fare_eur / rate, 2))

    # Status (0 confirmed, 1 cancelled, 2 no_show), cancellations and amendments.
    s_status = out["status"][sid]
    p_cancel = np.where(terminal, 0.003, np.where(seg == 2, 0.04, np.array([0.025, 0.055, 0.15])[rclass]))
    cancelled = (booked < std - 35 * MINUTE) & (rng.random(n) < p_cancel)
    p_noshow = np.where(
        terminal, 0.004, np.where(seg == 2, 0.005, np.where(seg == 0, 0.015, np.array([0.045, 0.025, 0.035])[rclass]))
    )
    noshow = ~cancelled & (s_status != 2) & ~onboard & (rng.random(n) < p_noshow)
    status = np.where(cancelled, 1, np.where(noshow, 2, 0))
    span = (std - 30 * MINUTE - booked).astype(np.int64)
    cancelled_at = np.where(
        cancelled,
        booked + (300 + rng.random(n) * np.maximum(span - 300, 0)).astype(np.int64) * second,
        np.datetime64("NaT"),
    )
    cancelled_at = skip_gap(cancelled_at)
    end = np.where(cancelled, cancelled_at, std - 60 * MINUTE)
    room = (end - booked).astype(np.int64)
    p_amend = np.where(terminal, 0.0, np.where(seg == 1, 0.045, np.where(seg == 0, 0.015, 0.008)))
    amended = (room > 1800) & (rng.random(n) < p_amend)
    amended_at = np.where(
        amended,
        booked + (600 + rng.random(n) * np.maximum(room - 600, 0)).astype(np.int64) * second,
        np.datetime64("NaT"),
    )
    amended_at = skip_gap(amended_at)
    # An amendment that moved to a dearer fare was paid as a top-up the booking does not record.
    topup = np.where(amended & (rng.random(n) < 0.65), np.round(amount * (0.08 + 0.37 * rng.random(n)), 2), 0.0)

    # Refunds (0 CXL, 1 SCX, 2 DLY, 3 GW), in the booking currency.
    s_day = days[sid]
    delay_s = np.where(s_status == 2, 0, (out["atd"][sid] - out["std_utc"][sid]).astype(np.int64))
    paid = amount + topup
    parts = []
    cxl = cancelled & (rclass > 0)
    cxl_amount = np.where(rclass == 2, paid, np.round(0.8 * paid, 2))
    parts.append(
        (
            np.flatnonzero(cxl),
            cancelled_at[cxl].astype("datetime64[D]") + rng.integers(0, 8, cxl.sum()),
            cxl_amount[cxl],
            0,
        )
    )
    scx = (s_status == 2) & (status == 0) & (rng.random(n) < 0.88)
    parts.append((np.flatnonzero(scx), s_day[scx] + rng.integers(1, 22, scx.sum()), paid[scx], 1))
    travelled = (status == 0) & (s_status != 2)
    dly = travelled & (delay_s >= 3600) & (rng.random(n) < 0.35)
    parts.append(
        (
            np.flatnonzero(dly),
            s_day[dly] + rng.integers(10, 61, dly.sum()),
            np.round(np.where(delay_s[dly] >= 7200, 0.5, 0.25) * amount[dly], 2),
            2,
        )
    )
    gw = travelled & (rng.random(n) < 0.0025)
    parts.append(
        (
            np.flatnonzero(gw),
            s_day[gw] + rng.integers(2, 46, gw.sum()),
            np.round((0.1 + 0.2 * rng.random(gw.sum())) * amount[gw], 2),
            3,
        )
    )
    r_book = np.concatenate([x[0] for x in parts])
    r_day = np.concatenate([x[1] for x in parts])
    r_amt = np.concatenate([x[2] for x in parts])
    r_reason = np.concatenate([np.full(len(x[0]), x[3]) for x in parts])
    # Some refunds are paid in two parts on different days.
    split = np.isin(r_reason, (0, 1)) & (rng.random(len(r_book)) < np.where(r_reason == 0, 0.10, 0.06))
    first = np.where(split, np.round(r_amt * (0.5 + 0.3 * rng.random(len(r_book))), 2), r_amt)
    s_idx = np.flatnonzero(split)
    r_book = np.r_[r_book, r_book[s_idx]]
    r_day = np.r_[r_day, r_day[s_idx] + rng.integers(3, 22, len(s_idx))]
    r_amt = np.r_[first, np.round((r_amt - first)[s_idx], 2)]
    r_reason = np.r_[r_reason, r_reason[s_idx]]
    positive = r_amt > 0
    r_book, r_day, r_amt, r_reason = r_book[positive], r_day[positive], r_amt[positive], r_reason[positive]

    # Channel codes: the legacy system wrote upper case; the app channel came with the new one.
    t_frac = np.clip(
        (booked - MIGRATION).astype(np.int64) / (np.datetime64("2025-12-31T00:00:00") - MIGRATION).astype(np.int64),
        0,
        1,
    )
    app = (chan == 0) & (booked >= MIGRATION) & (rng.random(n) < 0.05 + 0.35 * t_frac)
    channel_code = np.select([app, chan == 0, chan == 1, chan == 2], [1, 0, 2, 3], 4)
    legacy = booked < MIGRATION

    # Vehicle lengths as recorded: the legacy terminal software stored centimetres, and a few are missing.
    v_recorded = np.where(legacy[v_book] & terminal[v_book], np.round(v_len * 100), v_len)
    v_recorded = np.where(rng.random(len(v_book)) < 0.01, np.nan, v_recorded)

    return {
        "bookings": {
            "sailing": sid,
            "booked": booked,
            "channel": channel_code,
            "legacy": legacy,
            "currency": cur,
            "amount": amount,
            "status": status,
            "cancelled_at": cancelled_at,
            "amended_at": amended_at,
        },
        "passengers": {"booking": p_book, "seq": p_seq, "band": band, "fclass": fclass, "resident": resident},
        "vehicles": {"booking": v_book, "seq": v_seq, "cls": v_class, "length": v_recorded},
        "refunds": {"booking": r_book, "day": r_day, "amount": r_amt, "reason": r_reason},
    }


def vehicle_lengths(rng: np.random.Generator, motor: np.ndarray, caravan: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """True lengths in metres of the motor vehicle (by class) and of a caravan."""
    n = len(motor)
    u = rng.random(n)
    hgv = np.where(u < 0.5, 16.5, np.where(u < 0.7, 18.75, 10.0 + 2.0 * rng.random(n)))
    trl = np.where(rng.random(n) < 0.85, 13.6, 12.2)
    base = np.select(
        [motor == 0, motor == 1, motor == 2, motor == 4, motor == 6, motor == 7, motor == 8],
        [3.6 + 1.6 * u, 4.8 + 2.1 * u, 2.0 + 0.5 * u, 6.0 + 2.8 * u, hgv, trl, 12.0 + 1.5 * u],
        0.0,
    )
    cvn = np.where(caravan, 4.5 + 3.0 * rng.random(n), 0.0)
    return np.round(base, 2), np.round(cvn, 2)


# ---------- exchange rates ----------


def market_holidays(year: int) -> dict[str, set]:
    e = easter(year)
    day = lambda m, d: np.datetime64(f"{year}-{m:02d}-{d:02d}")  # noqa: E731
    td = lambda k: np.timedelta64(k, "D")  # noqa: E731
    common = {day(1, 1), day(12, 25), day(12, 26)}
    may = np.arange(day(5, 1), day(6, 1))
    mondays = [d for d in may if weekday(np.array([d]))[0] == 0]
    august = np.arange(day(8, 1), day(9, 1))
    aug_mondays = [d for d in august if weekday(np.array([d]))[0] == 0]
    midsummer = [d for d in np.arange(day(6, 19), day(6, 26)) if weekday(np.array([d]))[0] == 4][0]
    return {
        "NOK": common | {e - td(3), e - td(2), e + td(1), day(5, 1), day(5, 17), e + td(39), e + td(50)},
        "SEK": common | {e - td(2), e + td(1), day(5, 1), e + td(39), day(6, 6), midsummer, day(12, 24), day(12, 31)},
        "GBP": common | {e - td(2), e + td(1), mondays[0], mondays[-1], aug_mondays[-1]},
    }


def currency_rates(rng: np.random.Generator) -> dict[str, np.ndarray]:
    """Daily EUR value of one GBP, NOK and SEK: a mean-reverting random walk, not published on
    that currency's market holidays."""
    holidays = {c: set() for c in ("GBP", "NOK", "SEK")}
    for y in range(2021, 2026):
        for c, s in market_holidays(y).items():
            holidays[c] |= s
    start = {"GBP": 1.1650, "NOK": 0.0975, "SEK": 0.0985}
    centre = {"GBP": 1.1600, "NOK": 0.0890, "SEK": 0.0880}
    vol = {"GBP": 0.0032, "NOK": 0.0048, "SEK": 0.0041}
    decimals = {"GBP": 5, "NOK": 6, "SEK": 6}
    out_c, out_d, out_r = [], [], []
    for ci, c in enumerate(CURRENCIES[1:], start=1):
        shocks = rng.standard_normal(len(RATE_DAYS))
        level = np.log(start[c])
        for i, d in enumerate(RATE_DAYS):
            level += vol[c] * shocks[i] - 0.004 * (level - np.log(centre[c]))
            if d not in holidays[c]:
                out_c.append(ci)
                out_d.append(d)
                out_r.append(round(float(np.exp(level)), decimals[c]))
    return {"currency": np.array(out_c), "day": np.array(out_d, dtype="datetime64[D]"), "rate": np.array(out_r)}


# ---------- writing ----------


def booking_refs(n: int) -> np.ndarray:
    """Six-character references from a bijection of 0..n-1 onto 30-bit numbers."""
    alphabet = np.array(list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"))
    x = (np.arange(n, dtype=np.int64) * 0x2545F491 + 0x1F3A5C7) % (1 << 30)
    chars = [alphabet[(x >> (5 * i)) & 31] for i in range(5, -1, -1)]
    return np.char.add(
        np.char.add(np.char.add(chars[0], chars[1]), np.char.add(chars[2], chars[3])), np.char.add(chars[4], chars[5])
    ).astype(object)


def labels(values: np.ndarray, names: list) -> np.ndarray:
    return np.array(names, dtype=object)[values]


def write_tables(con: duckdb.DuckDBPyConnection) -> None:
    tt = timetable()
    warnings, worst, fog = weather(np.random.default_rng([SEED, 1]))
    out = sailing_outcomes(tt, worst, fog, np.random.default_rng([SEED, 2]))
    rates = currency_rates(np.random.default_rng([SEED, 3]))
    fx = filled_rates(rates)
    data = bookings(tt, out, fx, np.random.default_rng([SEED, 4]))

    con.execute("SET threads = 4")
    con.register(
        "h",
        {
            "harbour_code": np.array(CODES, dtype=object),
            "harbour_name": np.array([h[1] for h in HARBOURS], dtype=object),
            "isle": np.array([h[2] for h in HARBOURS], dtype=object),
            "district": np.array([h[3] for h in HARBOURS], dtype=object),
            "is_mainland": np.array([h[4] for h in HARBOURS]),
            "has_linkspan": np.array([h[5] for h in HARBOURS]),
            "tidal_restricted": np.array([h[6] for h in HARBOURS]),
            "berths": np.array([h[7] for h in HARBOURS], dtype=np.int16),
        },
    )
    con.execute("CREATE TABLE harbours AS SELECT * FROM h ORDER BY harbour_code")

    crossing_rows = []
    for code, name, a, b, nm, minutes, _, kind, *_ in SERVICES:
        for frm, to in ((a, b), (b, a)):
            crossing_rows.append(
                (
                    f"{frm}-{to}",
                    code,
                    name,
                    frm,
                    to,
                    nm,
                    minutes,
                    "summer" if kind == "seasonal" else "all_year",
                    kind,
                    "2024-05-01" if code == "S12" else None,
                )
            )
    cr = list(zip(*crossing_rows))
    con.register(
        "c",
        {
            "crossing_code": np.array(cr[0], dtype=object),
            "service_code": np.array(cr[1], dtype=object),
            "service_name": np.array(cr[2], dtype=object),
            "from_harbour": np.array(cr[3], dtype=object),
            "to_harbour": np.array(cr[4], dtype=object),
            "distance_nm": np.array(cr[5], dtype=float),
            "timetable_minutes": np.array(cr[6], dtype=np.int16),
            "season": np.array(cr[7], dtype=object),
            "service_type": np.array(cr[8], dtype=object),
            "launched_on": np.array(cr[9], dtype=object),
        },
    )
    con.execute("""CREATE TABLE crossings AS SELECT crossing_code, service_code, service_name, from_harbour, to_harbour,
        distance_nm, timetable_minutes, season, service_type, CAST(launched_on AS DATE) AS launched_on
        FROM c ORDER BY crossing_code""")

    fl = list(zip(*FLEET))
    con.register(
        "f",
        {
            "vessel_code": np.array(fl[0], dtype=object),
            "vessel_name": np.array(fl[1], dtype=object),
            "vessel_type": np.array(fl[2], dtype=object),
            "year_built": np.array(fl[3], dtype=np.int16),
            "gross_tonnage": np.array(fl[4], dtype=np.int32),
            "pax_cert_summer": np.array(fl[5], dtype=np.int16),
            "pax_cert_winter": np.array(fl[6], dtype=np.int16),
            "lane_metres": np.array(fl[7], dtype=np.int16),
            "crew_complement": np.array(fl[8], dtype=np.int16),
            "service_speed_kn": np.array(fl[9], dtype=float),
            "joined_fleet": np.array(fl[10], dtype=object),
            "left_fleet": np.array(fl[11], dtype=object),
        },
    )
    con.execute("""CREATE TABLE fleet AS SELECT vessel_code, vessel_name, vessel_type, year_built, gross_tonnage,
        pax_cert_summer, pax_cert_winter, lane_metres, crew_complement, service_speed_kn,
        CAST(joined_fleet AS DATE) AS joined_fleet, CAST(left_fleet AS DATE) AS left_fleet
        FROM f ORDER BY vessel_code""")

    con.register(
        "r",
        {
            "currency": labels(rates["currency"], CURRENCIES),
            "rate_date": rates["day"].astype("datetime64[s]"),
            "eur_per_unit": rates["rate"],
        },
    )
    con.execute(
        "CREATE TABLE currency_rates AS SELECT currency, CAST(rate_date AS DATE) AS rate_date, eur_per_unit FROM r ORDER BY currency, rate_date"
    )

    w_order = np.lexsort((warnings["hazard"], warnings["port"], warnings["issued"]))
    con.register(
        "w",
        {
            "warning_id": np.arange(1, len(w_order) + 1, dtype=np.int32),
            "harbour_code": labels(warnings["port"][w_order], CODES),
            "valid_on": DAYS[warnings["day"][w_order]].astype("datetime64[s]"),
            "hazard": labels(warnings["hazard"][w_order], HAZARDS),
            "level": labels(warnings["level"][w_order], LEVELS),
            "issued_at": warnings["issued"][w_order],
            "max_gust_kn": np.where(warnings["gust"][w_order] < 0, np.nan, warnings["gust"][w_order]),
        },
    )
    con.execute("""CREATE TABLE met_warnings AS SELECT warning_id, harbour_code, CAST(valid_on AS DATE) AS valid_on, hazard,
        level, CAST(issued_at AS TIMESTAMP) AS issued_at, CAST(max_gust_kn AS SMALLINT) AS max_gust_kn FROM w ORDER BY warning_id""")

    s_order = np.lexsort((tt["service"] * 100 + tt["frm"], tt["std"]))
    sailing_id = np.empty(len(s_order), dtype=np.int32)
    sailing_id[s_order] = np.arange(1, len(s_order) + 1)
    crossing = np.char.add(np.char.add(np.array(CODES)[tt["frm"]], "-"), np.array(CODES)[tt["to"]]).astype(object)
    con.register(
        "s",
        {
            "sailing_id": sailing_id,
            "crossing_code": crossing,
            "vessel_code": labels(tt["vessel"], [v[0] for v in FLEET]),
            "std_local": tt["std"],
            "sta_local": tt["sta"],
            "std_utc_offset": out["std_off"],
            "sta_utc_offset": out["sta_off"],
            "atd_utc": out["atd"],
            "ata_utc": out["ata"],
            "sailing_status": labels(out["status"], ["sailed", "diverted", "cancelled"]),
            "arrived_at": np.where(out["arrived"] >= 0, np.array(CODES + [None], dtype=object)[out["arrived"]], None),
            "cancel_code": labels(out["cancel"], CANCEL_CODES),
        },
    )
    con.execute("""CREATE TABLE sailings AS SELECT sailing_id, crossing_code, vessel_code,
        CAST(std_local AS TIMESTAMP) AS std_local, CAST(sta_local AS TIMESTAMP) AS sta_local,
        CAST(std_utc_offset AS SMALLINT) AS std_utc_offset, CAST(sta_utc_offset AS SMALLINT) AS sta_utc_offset,
        CAST(atd_utc AS TIMESTAMP) AS atd_utc, CAST(ata_utc AS TIMESTAMP) AS ata_utc, sailing_status, arrived_at, cancel_code
        FROM s ORDER BY sailing_id""")

    b = data["bookings"]
    nb = len(b["sailing"])
    refs = booking_refs(nb)
    channel = np.where(b["legacy"], labels(b["channel"], CHANNELS_OLD), labels(b["channel"], CHANNELS_NEW))
    con.register(
        "b",
        {
            "booking_no": np.arange(nb, dtype=np.int32),
            "booking_ref": refs,
            "sailing_id": sailing_id[b["sailing"]],
            "booked_at": b["booked"],
            "channel": channel,
            "currency": labels(b["currency"], CURRENCIES),
            "fare_total": b["amount"],
            "booking_status": labels(b["status"], ["confirmed", "cancelled", "no_show"]),
            "cancelled_at": b["cancelled_at"],
            "amended_at": b["amended_at"],
        },
    )
    p = data["passengers"]
    con.register(
        "p",
        {
            "booking_no": p["booking"].astype(np.int32),
            "seq": p["seq"].astype(np.int16),
            "age_band": labels(p["band"], AGE_BANDS),
            "fare_class": labels(p["fclass"], FARE_CLASSES),
            "is_resident": p["resident"].astype(bool),
        },
    )
    con.execute("""CREATE TABLE bookings AS
        WITH party AS (
          SELECT booking_no, list({'age_band': age_band, 'fare_class': fare_class, 'is_resident': is_resident} ORDER BY seq) AS passengers
          FROM p GROUP BY booking_no
        )
        SELECT b.booking_ref, b.sailing_id, CAST(b.booked_at AS TIMESTAMP) AS booked_at, b.channel, b.currency,
          CAST(b.fare_total AS DECIMAL(10, 2)) AS fare_total, b.booking_status,
          CAST(b.cancelled_at AS TIMESTAMP) AS cancelled_at, CAST(b.amended_at AS TIMESTAMP) AS amended_at,
          coalesce(party.passengers, CAST([] AS STRUCT(age_band VARCHAR, fare_class VARCHAR, is_resident BOOLEAN)[])) AS passengers
        FROM b LEFT JOIN party USING (booking_no)
        ORDER BY b.booking_no""")

    v = data["vehicles"]
    con.register(
        "v",
        {
            "vehicle_id": np.arange(1, len(v["booking"]) + 1, dtype=np.int32),
            "booking_ref": refs[v["booking"]],
            "vehicle_seq": v["seq"].astype(np.int16),
            "vehicle_class": labels(v["cls"], VEHICLE_CLASSES),
            "length_m": v["length"],
        },
    )
    con.execute("CREATE TABLE booked_vehicles AS SELECT * FROM v ORDER BY vehicle_id")

    rf = data["refunds"]
    r_order = np.lexsort((rf["reason"], rf["booking"], rf["day"]))
    con.register(
        "rf",
        {
            "refund_id": np.arange(1, len(r_order) + 1, dtype=np.int32),
            "booking_ref": refs[rf["booking"][r_order]],
            "refunded_on": rf["day"][r_order].astype("datetime64[s]"),
            "refund_amount": rf["amount"][r_order],
            "currency": labels(b["currency"][rf["booking"][r_order]], CURRENCIES),
            "reason_code": labels(rf["reason"][r_order], REFUND_REASONS),
        },
    )
    con.execute("""CREATE TABLE refunds AS SELECT refund_id, booking_ref, CAST(refunded_on AS DATE) AS refunded_on,
        CAST(refund_amount AS DECIMAL(10, 2)) AS refund_amount, currency, reason_code FROM rf ORDER BY refund_id""")
    for name in ("h", "c", "f", "r", "w", "s", "b", "p", "v", "rf"):
        con.unregister(name)
