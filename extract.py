"""
Extract ICU Liberation Bundle events from eICU nurseCharting into native eICU format.

Zero dependency on MIMIC-IV. Uses standard FHIR column 'code' with eICU's own labels,
which are resolved to standard LOINC/SNOMED by fhir/eicu-to-standard.conceptmap.json.

Usage:
    python extract.py
    python extract.py --stays 5
"""
import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CM_PATH = os.path.join(HERE, "fhir", "eicu-to-standard.conceptmap.json")

def load_eicu_concepts():
    cm = json.load(open(CM_PATH, encoding="utf-8"))
    return {el["code"].lower(): el.get("display", el["code"])
            for g in cm.get("group", []) for el in g.get("element", [])}

def main(stays=5, src="nurseCharting.csv", dst="eicu.csv"):
    src_path = os.path.join(HERE, src)
    dst_path = os.path.join(HERE, dst)

    if not os.path.isfile(src_path):
        print(f"Error: {src_path} not found")
        return

    known_labels = load_eicu_concepts()
    print(f"Loaded {len(known_labels)} eICU bundle concepts from fhir/eicu-to-standard.conceptmap.json")
    print(f"Reading {src} to find top {stays} stays...")

    # 1. Count bundle events per patient stay
    stay_counts = defaultdict(int)
    with open(src_path, "r", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            label = row.get("nursingchartcelltypevallabel", "").strip().lower()
            if label in known_labels:
                stay_counts[row["patientunitstayid"]] += 1

    top_stays = set(sorted(stay_counts, key=stay_counts.get, reverse=True)[:stays])
    print(f"Selected stays: {', '.join(sorted(top_stays))}")

    # 2. Extract and format rows with native eICU code (NO itemid)
    base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    extracted = []

    with open(src_path, "r", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            pid = row.get("patientunitstayid")
            if pid not in top_stays:
                continue
            label = row.get("nursingchartcelltypevallabel", "").strip().lower()
            if label not in known_labels:
                continue

            offset_min = int(row.get("nursingchartoffset", 0))
            charttime = (base_time + timedelta(minutes=offset_min)).strftime("%Y-%m-%d %H:%M:%S")

            extracted.append({
                "subject_id": pid,
                "code": label,
                "charttime": charttime,
            })

    # 3. Save to eicu.csv using standard column names: subject_id, code, charttime
    with open(dst_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["subject_id", "code", "charttime"])
        writer.writeheader()
        writer.writerows(extracted)

    print(f"Saved {len(extracted):,} rows across {len(top_stays)} stays to {dst}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stays", type=int, default=5, help="Number of top stays to extract")
    parser.add_argument("--src", default="nurseCharting.csv", help="Input file")
    parser.add_argument("--dst", default="eicu.csv", help="Output file")
    args = parser.parse_args()
    main(stays=args.stays, src=args.src, dst=args.dst)
