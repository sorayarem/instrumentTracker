from __future__ import annotations

import csv
import json
import sys
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVAL_CSV_PATH = ROOT / "data" / "detections" / "dmonDailyCounts.csv"
REALTIME_CSV_PATH = ROOT / "data" / "detections" / "dmonDetectDailyCounts.csv"
MISSIONS_PATH = ROOT / "data" / "missions.json"
OUT_PATH = ROOT / "public" / "data" / "matrix.json"

DETECTION_SOURCES = [
    {
        "key": "realTime",
        "label": "Real-time (days)",
        "path": REALTIME_CSV_PATH,
        "unit": "days",
    },
    {
        "key": "archival",
        "label": "Archival (calls)",
        "path": ARCHIVAL_CSV_PATH,
        "unit": "calls",
    },
    {
        "key": "archivalDays",
        "label": "Archival (days)",
        "path": ARCHIVAL_CSV_PATH,
        "unit": "days",
    },
]

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


def column_detection_meta(name: str) -> tuple[str, str] | None:
    for prefix, instrument in INSTRUMENTS.items():
        if not name.startswith(prefix):
            continue
        suffix = name.removeprefix(prefix).lower()
        if suffix in {"detected", "possible"}:
            return instrument, suffix
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


def empty_detection_bucket() -> dict:
    return {
        "hasData": False,
        "dates": set(),
        "detected": 0,
        "possible": 0,
        "sources": {
            source["key"]: {
                "label": source["label"],
                "hasData": False,
                "dates": set(),
                "detected": 0,
                "possible": 0,
            }
            for source in DETECTION_SOURCES
        },
    }


def parse_detection_cell(source: dict, raw: str) -> int | None:
    if not raw or raw.upper() == "NA":
        return None

    try:
        value = float(raw)
    except ValueError:
        return None

    if source["unit"] == "days":
        return 1 if value > 0 else 0

    return int(value)


def add_detection_value(
    bucket: dict,
    source: dict,
    parsed: date,
    kind: str,
    value: int,
) -> None:
    source_bucket = bucket["sources"][source["key"]]

    bucket["hasData"] = True
    bucket["dates"].add(parsed)
    bucket[kind] += value

    source_bucket["hasData"] = True
    source_bucket["dates"].add(parsed)
    source_bucket[kind] += value


def read_detection_csv(
    source: dict,
    agg: dict[tuple[str, str, str], dict],
) -> list[dict]:
    path = source["path"]
    if not path.exists():
        return []

    col_map: dict[str, tuple[str, str]] = {}
    records: list[dict] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for column in reader.fieldnames or []:
            if column == "date":
                continue
            meta = column_detection_meta(column)
            if meta:
                col_map[column] = meta

    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            parsed = parse_date(row.get("date", ""))
            if not parsed:
                continue

            acoustic_year = calendar_to_acoustic_year(parsed)
            month = calendar_month_name(parsed.month)

            if source["unit"] == "days":
                daily_values: dict[str, dict[str, int]] = {}

                for column, (instrument, kind) in col_map.items():
                    raw = (row.get(column) or "").strip()
                    value = parse_detection_cell(source, raw)
                    if value is None:
                        continue

                    values = daily_values.setdefault(
                        instrument,
                        {"detected": 0, "possible": 0},
                    )
                    values[kind] = max(values[kind], value)

                for instrument, values in daily_values.items():
                    if values["detected"] > 0:
                        kind = "detected"
                        value = 1
                    elif values["possible"] > 0:
                        kind = "possible"
                        value = 1
                    else:
                        kind = "detected"
                        value = 0

                    key = (instrument, acoustic_year, month)
                    add_detection_value(agg[key], source, parsed, kind, value)
                    records.append(
                        {
                            "source": source,
                            "instrument": instrument,
                            "date": parsed,
                            "kind": kind,
                            "value": value,
                        }
                    )

                continue

            for column, (instrument, kind) in col_map.items():
                raw = (row.get(column) or "").strip()
                value = parse_detection_cell(source, raw)
                if value is None:
                    continue

                key = (instrument, acoustic_year, month)
                add_detection_value(agg[key], source, parsed, kind, value)
                records.append(
                    {
                        "source": source,
                        "instrument": instrument,
                        "date": parsed,
                        "kind": kind,
                        "value": value,
                    }
                )

    return records


def mission_contains_date(mission: dict, parsed: date, today: date) -> bool:
    for window in mission["windows"]:
        start = parse_date(window["start"])
        end = parse_mission_end(window["end"], today)
        if start and end and start <= parsed <= end:
            return True
    return False


def attach_mission_detection_summaries(
    missions: list[dict],
    records: list[dict],
    today: date,
) -> None:
    buckets = {mission["id"]: empty_detection_bucket() for mission in missions}

    for record in records:
        for mission in missions_for_instrument(missions, record["instrument"]):
            if not mission_contains_date(mission, record["date"], today):
                continue
            add_detection_value(
                buckets[mission["id"]],
                record["source"],
                record["date"],
                record["kind"],
                record["value"],
            )

    for mission in missions:
        summary = detection_summary(buckets[mission["id"]])
        if summary:
            mission["detections"] = summary
        else:
            mission.pop("detections", None)


def detection_summary(stats: dict) -> list[dict]:
    return [
        {
            "source": source_key,
            "label": source["label"],
            "daysWithData": len(source["dates"]),
            "detected": source["detected"],
            "possible": source["possible"],
        }
        for source_key, source in stats["sources"].items()
        if source["hasData"]
    ]


def build_matrix() -> dict:
    if not ARCHIVAL_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing CSV: {ARCHIVAL_CSV_PATH}")

    missions = load_missions()
    today = date.today()

    agg: dict[tuple[str, str, str], dict] = defaultdict(empty_detection_bucket)
    detection_records: list[dict] = []
    for source in DETECTION_SOURCES:
        detection_records.extend(read_detection_csv(source, agg))
    attach_mission_detection_summaries(missions, detection_records, today)

    years = collect_acoustic_years(agg, missions, today)

    instruments = []
    for instrument in INSTRUMENT_ORDER:
        cells = []
        for acoustic_year in years:
            for month in MONTHS:
                stats = agg.get(
                    (instrument, acoustic_year, month),
                    empty_detection_bucket(),
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
                    "daysWithData": len(stats["dates"]),
                    "totalDetections": stats["detected"] + stats["possible"],
                    "detections": detection_summary(stats),
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
