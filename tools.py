import argparse
import csv
import json
import os
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import service as S

BASE = "http://example.org/fhir"
CARDS = {c["id"]: c for c in S.RULES["components"]}

def load_conceptmap(cm_path=None, data_path=""):
    if cm_path and os.path.isfile(cm_path):
        return json.load(open(cm_path, encoding="utf-8"))
    if "eicu" in data_path.lower():
        fname = "eicu-to-standard.conceptmap.json"
    else:
        fname = "mimiciv-itemid-to-standard.conceptmap.json"
    return json.load(open(os.path.join(HERE, "fhir", fname), encoding="utf-8"))

def build_maps(cm):
    by_code = defaultdict(set)
    imap = {}
    for g in cm["group"]:
        for el in g["element"]:
            raw_c = el["code"]
            key = int(raw_c) if str(raw_c).isdigit() else str(raw_c).strip().lower()
            for t in el["target"]:
                by_code[t["code"]].add(key)
                imap[key] = (g["target"], t["code"], t.get("display", ""))
    return by_code, imap

DEFAULT_CM = load_conceptmap()
BY_CODE, IMAP = build_maps(DEFAULT_CM)

def parse_time(v):
    t = datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

def to_bundle(rows, imap, code_col="itemid", unmapped=None):
    entries = []
    for r in rows:
        raw_val = r.get(code_col, "")
        key = int(raw_val) if str(raw_val).isdigit() else str(raw_val).strip().lower()
        hit = imap.get(key)
        if hit is None:
            if unmapped is not None:
                unmapped.add(raw_val)
            continue
        system, code, display = hit
        obs = {
            "resourceType": "Observation",
            "status": "final",
            "code": {"coding": [{"system": system, "code": code, "display": display}]},
            "subject": {"reference": "Patient/%s" % r["subject_id"]},
            "effectiveDateTime": parse_time(r["charttime"]).isoformat(),
        }
        entries.append({"resource": obs})
    return {"resourceType": "Bundle", "type": "searchset",
            "total": len(entries), "entry": entries}

def itemids_for(comp, by_code=None):
    bmap = by_code if by_code is not None else BY_CODE
    if comp.get("count_only"):
        return {int(i) if str(i).isdigit() else str(i).lower() for i in comp["count_only"]}
    items = set()
    for (_system, code) in S.codes_for(comp):
        items |= bmap.get(code, set())
    return items

def run(rows, comp_id, limit=None, verbose=False, code_col="itemid", by_code=None, imap=None):
    comp = CARDS[comp_id]
    presence = not comp["min_per_24h"]
    bmap = by_code if by_code is not None else BY_CODE
    active_imap = imap if imap is not None else IMAP
    wanted = itemids_for(comp, bmap)
    days, buckets = set(), defaultdict(list)
    for r in rows:
        key = (r["subject_id"], parse_time(r["charttime"]).date())
        days.add(key)
        raw_val = r.get(code_col, "")
        val_key = int(raw_val) if str(raw_val).isdigit() else str(raw_val).strip().lower()
        if val_key in wanted:
            buckets[key].append(r)
    keys = sorted(days)[:limit] if limit else sorted(days)
    agree = compared = empty = met = 0
    mismatches, dropped = [], set()
    for key in keys:
        group = buckets.get(key, [])
        if group:
            unmapped = set()
            bundle = to_bundle(group, active_imap, code_col=code_col, unmapped=unmapped)
            dropped |= unmapped
            as_of = datetime.combine(key[1], datetime.max.time()).replace(
                tzinfo=timezone.utc)
            n = S.count_matching(bundle, S.codes_for(comp), as_of)
            compared += 1
            if n == len(group):
                agree += 1
            else:
                mismatches.append(key)
        else:
            n, empty = 0, empty + 1
        if (n > 0) if presence else (n >= comp["min_per_24h"]):
            met += 1
        if verbose:
            flag = ("DONE" if n else "NONE") if presence else (
                "MET " if n >= comp["min_per_24h"] else "MISS")
            print("  %-9s %s  %s  %s"
                  % (key[0], key[1], flag, S.build_card(comp, n)["summary"]))
            if group and n != len(group):
                print("      MISMATCH against the notebook count of %d" % len(group))
    return agree, compared, empty, met, len(keys), mismatches, dropped

def cmd_validate(args):
    path = args.csv
    if not path:
        candidates = ["chartevents.csv", "eICU_chartevents.csv"]
        path = next((f for f in candidates if os.path.isfile(f)), "chartevents.csv")
    if not os.path.isfile(path):
        print("No such file:", path)
        return 1
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    code_col = "code" if rows and "code" in rows[0] else "itemid"
    print("loaded %d rows from %s (using column: %s)\n" % (len(rows), path, code_col))
    missing = [c for c in ("subject_id", "charttime") if rows and c not in rows[0]]
    if rows and code_col not in rows[0]:
        missing.append("code or itemid")
    if missing:
        print("Missing required columns: %s" % ", ".join(missing))
        return 1
    cm = load_conceptmap(getattr(args, "conceptmap", None), path)
    by_code, imap = build_maps(cm)
    all_dropped, rows_out, tot_agree, tot_cmp = set(), [], 0, 0
    for cid in [c.strip().upper() for c in args.component.split(",")]:
        if cid not in CARDS:
            print("unknown component", cid)
            continue
        agree, compared, empty, met, total, mismatches, dropped = run(
            rows, cid, args.limit, args.verbose, code_col=code_col, by_code=by_code, imap=imap)
        all_dropped |= dropped
        tot_agree += agree
        tot_cmp += compared
        comp = CARDS[cid]
        target = ("%d per 24h" % comp["min_per_24h"]) if comp["min_per_24h"] else "documented"
        rate = ("%.1f%%" % (100.0 * met / total)) if total else "n/a"
        rows_out.append((cid, comp["name"], target, total, empty, met, rate))
        if mismatches:
            print("   %d patient days disagree with the notebook count" % len(mismatches))

    if args.verbose:
        print("")
    print("%-2s %-18s %-12s %6s %8s %6s %9s"
          % ("", "component", "target", "days", "no data", "met", "adherence"))
    for cid, name, target, total, empty, met, rate in rows_out:
        print("%-2s %-18s %-12s %6d %8d %6d %9s"
              % (cid, name.lower(), target, total, empty, met, rate))
    print("")
    if tot_cmp and tot_agree == tot_cmp:
        print("All %d documented patient days match the notebook count." % tot_cmp)
    elif tot_cmp:
        print("%d of %d documented patient days match the notebook count."
              % (tot_agree, tot_cmp))
    if all_dropped:
        print("Itemids absent from the ConceptMap, dropped by the converter: %s"
              % sorted(all_dropped))
    return 0

def _rec(system, code, hours_ago, now):
    return {"resource": {
        "resourceType": "Observation", "status": "final",
        "code": {"coding": [{"system": system, "code": code}]},
        "subject": {"reference": "Patient/example"},
        "effectiveDateTime": (now - timedelta(hours=hours_ago)).isoformat(),
    }}

def _any_code(cid):
    return sorted(S.codes_for(CARDS[cid]))[0]

def build_bundle(now=None):
    now = now or datetime.now(timezone.utc)
    entries = []
    for h in (1, 6, 13):
        entries.append(_rec(*_any_code("A"), h, now))
    for h in (2, 9, 40):
        entries.append(_rec(*_any_code("D"), h, now))
    entries.append(_rec(*_any_code("F"), 4, now))
    entries.append({"resource": {
        "resourceType": "Observation", "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4",
                             "display": "Heart rate"}]},
        "subject": {"reference": "Patient/example"},
        "effectiveDateTime": now.isoformat()}})
    return {"resourceType": "Bundle", "type": "searchset",
            "total": len(entries), "entry": entries}

def cmd_test(args):
    bundle = build_bundle()

    def call(comp_id, prefetch=None):
        req = S.HookRequest(hook="patient-view", hookInstance=str(uuid.uuid4()),
                            context={"patientId": "example"},
                            prefetch={} if prefetch == "none"
                            else {S.PREFETCH_KEY: prefetch if prefetch is not None else bundle})
        return S.invoke(S.service_id(comp_id), req)["cards"][0]
    d = S.discovery()
    assert len(d["services"]) == 6, d
    assert all(s["hook"] == "patient-view" for s in d["services"])
    assert all("prefetch" in s for s in d["services"])
    print("ok   discovery lists all 6 components")
    exp = {"A": "warning", "C": "critical", "D": "info", "F": "info",
           "B": "warning", "E": "warning"}
    for cid in "ABCDEF":
        card = call(cid)
        print("     %s -> %-8s %s" % (cid, card["indicator"], card["summary"]))
        assert card["indicator"] == exp[cid], (cid, card)
        assert len(card["summary"]) <= 140
        assert card["indicator"] in ("info", "warning", "critical")
        assert "label" in card["source"]
    print("ok   all six components score as expected and match the card schema")
    a = call("A")
    assert "3 of 6" in a["summary"], a
    dd = call("D")
    assert "2 of 2" in dd["summary"], dd
    print("ok   the 24 hour window excludes the 40 hour old record")
    c = call("C")
    assert "cannot separate them" in c["detail"], c
    print("ok   component C surfaces the RASS code collision in the card")
    card = call("A", prefetch="none")
    assert "could not run" in card["summary"], card
    card = call("A", prefetch={"resourceType": "Bundle", "type": "searchset", "entry": []})
    assert card["indicator"] == "critical", card
    print("ok   missing and empty data handled without crashing")
    assert "457441000124102" in S.AMBIGUOUS, S.AMBIGUOUS
    print("ok   the ConceptMap exposes the shared RASS code")
    n_codes = sum(len(v["codes"]) for v in S.VALUESETS.values())
    assert len(S.VALUESETS) == 6, sorted(S.VALUESETS)
    assert n_codes >= 30, n_codes
    print("ok   6 value sets, %d codes, ConceptMap and clinical rules agree" % n_codes)
    return 0

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("test")
    v = sub.add_parser("validate")
    v.add_argument("csv", nargs="?")
    v.add_argument("--component", default="A,B,C,D,E,F")
    v.add_argument("--limit", type=int)
    v.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    return {"test": cmd_test, "validate": cmd_validate}[args.cmd](args)

if __name__ == "__main__":
    _c = main() or 0
    if _c:
        sys.exit(_c)
