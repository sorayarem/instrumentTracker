"""Build public/data/matrix.json from dmonDailyCounts.csv and archived mission windows."""

from __future__ import annotations

import csv
import json
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "detections" / "dmonDailyCounts.csv"
MISSIONS_PATH = ROOT / "data" / "missions.json"
OUT_PATH = ROOT / "public" / "data" / "matrix.json"

INSTRUMENTS = {
    "glider": "Glider",
    "shallow": "Soundtrap (Shallow)",
    "mid": "Soundtrap (Mid)",
    "deep": "Soundtrap (Deep)",
    "gasvBuoy": "GASV Buoy",
    "vanfBuoy": "VANF Buoy",
}

INSTRUMENT_ORDER = [
    "Glider",
    "Soundtrap (Shallow)",
    "GASV Buoy",
    "Soundtrap (Mid)",
    "VANF Buoy",
    "Soundtrap (Deep)",
]

COLORS = {
    "Glider": "#1F3B8A",
    "VANF Buoy": "#FD8D3C",
    "GASV Buoy": "#3EA6C6",
    "Soundtrap (Shallow)": "#66C2A3",
    "Soundtrap (Mid)": "#CCE596",
    "Soundtrap (Deep)": "#990000",
}

LABELS = {
    "Glider": "Glider",
    "VANF Buoy": "Norfolk Buoy",
    "GASV Buoy": "Savannah Buoy",
    "Soundtrap (Shallow)": "Shallow Soundtrap",
    "Soundtrap (Mid)": "Mid Soundtrap",
    "Soundtrap (Deep)": "Deep Soundtrap",
}

MONTHS = ["Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct"]

MONTH_TO_CAL = {
    "Nov": 11,
    "Dec": 12,
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
}


def parse_date(value: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def column_instrument(name: str) -> str | None:
    for prefix, instrument in INSTRUMENTS.items():
        if name.startswith(prefix):
            return instrument
    return None


def calendar_month_name(cal_month: int) -> str:
    return MONTHS[(cal_month - 11) % 12]


def calendar_to_acoustic_year(value: date) -> str:
    yy = value.year % 100
    if value.month >= 11:
        return f"{yy:02d}-{yy + 1:02d}"
    return f"{yy - 1:02d}-{yy:02d}"


def acoustic_year_sort_key(label: str) -> int:
    return int(label.split("-")[0])


def cell_calendar_bounds(acoustic_year: str, month_name: str) -> tuple[date, date]:
    start_yy = int(acoustic_year.split("-")[0])
    start_year = 2000 + start_yy
    cal_month = MONTH_TO_CAL[month_name]
    cal_year = start_year if month_name in ("Nov", "Dec") else start_year + 1
    last_day = monthrange(cal_year, cal_month)[1]
    return date(cal_year, cal_month, 1), date(cal_year, cal_month, last_day)


def load_missions() -> list[dict]:
    if not MISSIONS_PATH.exists():
        return []
    payload = json.loads(MISSIONS_PATH.read_text(encoding="utf-8"))
    return payload.get("missions", [])


def missions_for_instrument(missions: list[dict], instrument: str) -> list[dict]:
    return [mission for mission in missions if mission["instrument"] == instrument]


def parse_mission_end(value: str, today: date) -> date | None:
    if value.strip().lower() == "present":
        return today
    return parse_date(value)


def ranges_overlap(range_start: date, range_end: date, window_start: date, window_end: date) -> bool:
    return range_start <= window_end and range_end >= window_start


def acoustic_years_for_range(start: date, end: date) -> set[str]:
    years: set[str] = set()
    cursor = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)

    while cursor <= end_month:
        years.add(calendar_to_acoustic_year(cursor))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    return years


def find_mission_matches(
    instrument: str,
    acoustic_year: str,
    month_name: str,
    missions: list[dict],
    today: date,
) -> list[tuple[dict, dict]]:
    month_start, month_end = cell_calendar_bounds(acoustic_year, month_name)
    matches: list[tuple[dict, dict]] = []

    for mission in missions_for_instrument(missions, instrument):
        for window in mission["windows"]:
            start = parse_date(window["start"])
            end = parse_mission_end(window["end"], today)
            if not start or not end:
                continue
            if ranges_overlap(month_start, month_end, start, end):
                matches.append((mission, window))

    return matches


def window_label(window: dict) -> str:
    if "label" in window:
        return window["label"]
    end = window["end"].strip().lower()
    if end == "present":
        return f"{window['start']} – present"
    return f"{window['start']} – {window['end']}"


def cell_status(instrument: str, has_data: bool, mission: dict | None) -> str:
    if instrument.startswith("Soundtrap"):
        return "available" if has_data and mission else "inactive"

    if not mission:
        return "inactive"

    return "available" if has_data else "listening"


def collect_acoustic_years(
    agg: dict[tuple[str, str, str], dict],
    missions: list[dict],
    today: date,
) -> list[str]:
    years = {key[1] for key in agg}

    for mission in missions:
        for window in mission["windows"]:
            start = parse_date(window["start"])
            end = parse_mission_end(window["end"], today)
            if start and end:
                years.update(acoustic_years_for_range(start, end))

    return sorted(years, key=acoustic_year_sort_key)


def build_matrix() -> dict:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Missing CSV: {CSV_PATH}")

    missions = load_missions()
    today = date.today()

    col_map: dict[str, str] = {}
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for column in reader.fieldnames or []:
            if column == "date":
                continue
            instrument = column_instrument(column)
            if instrument:
                col_map[column] = instrument

    agg: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {"hasData": False, "daysWithData": 0, "totalDetections": 0}
    )

    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            parsed = parse_date(row.get("date", ""))
            if not parsed:
                continue

            acoustic_year = calendar_to_acoustic_year(parsed)
            month = calendar_month_name(parsed.month)

            for column, instrument in col_map.items():
                raw = (row.get(column) or "").strip()
                key = (instrument, acoustic_year, month)
                if not raw or raw.upper() == "NA":
                    continue

                bucket = agg[key]
                bucket["hasData"] = True
                bucket["daysWithData"] += 1
                try:
                    bucket["totalDetections"] += int(float(raw))
                except ValueError:
                    pass

    years = collect_acoustic_years(agg, missions, today)

    instruments = []
    for instrument in INSTRUMENT_ORDER:
        cells = []
        for acoustic_year in years:
            for month in MONTHS:
                stats = agg.get(
                    (instrument, acoustic_year, month),
                    {"hasData": False, "daysWithData": 0, "totalDetections": 0},
                )
                matches = find_mission_matches(
                    instrument, acoustic_year, month, missions, today
                )
                mission = matches[0][0] if matches else None
                window = matches[0][1] if matches else None
                status = cell_status(instrument, stats["hasData"], mission)
                cell = {
                    "year": acoustic_year,
                    "month": month,
                    "status": status,
                    "daysWithData": stats["daysWithData"],
                    "totalDetections": stats["totalDetections"],
                }
                if mission and window:
                    cell["missionId"] = mission["id"]
                    cell["missionLabel"] = mission["label"]
                    cell["missionColor"] = mission["color"]
                    cell["missionDates"] = window_label(window)
                    if len(matches) > 1:
                        cell["missionIds"] = [match[0]["id"] for match in matches]
                elif status == "available":
                    cell["missionColor"] = COLORS[instrument]

                cells.append(cell)

        instruments.append(
            {
                "id": instrument.lower().replace(" ", "-").replace("(", "").replace(")", ""),
                "name": instrument,
                "label": LABELS[instrument],
                "color": COLORS[instrument],
                "cells": cells,
            }
        )

    return {
        "title": "Data Availability by Instrument, Month, and Year",
        "months": MONTHS,
        "years": years,
        "missions": missions,
        "instruments": instruments,
    }


def main() -> int:
    payload = build_matrix()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({len(payload['instruments'])} instruments, years {payload['years']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
