import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from fastapi import FastAPI
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
FHIR = os.path.join(HERE, "fhir")
PREFETCH_KEY = "obs24h"

def load_valuesets():
    out = {}
    for name in sorted(os.listdir(FHIR)):
        if not name.endswith(".valueset.json"):
            continue
        vs = json.load(open(os.path.join(FHIR, name), encoding="utf-8"))
        codes, displays = set(), {}
        for inc in vs.get("compose", {}).get("include", []):
            system = inc.get("system", "")
            for c in inc.get("concept", []):
                codes.add((system, c["code"]))
                displays.setdefault(c["code"], c.get("display", ""))
        out[vs["url"]] = {"codes": codes, "displays": displays, "title": vs.get("title", "")}
    return out

VALUESETS = load_valuesets()
RULES = json.load(open(os.path.join(HERE, "rules.json"), encoding="utf-8"))
COMPONENTS = {c["id"]: c for c in RULES["components"]}

def service_id(comp_id: str) -> str:
    return "icu-liberation-%s" % comp_id.lower()

def codes_for(comp: Dict[str, Any]) -> Set[Tuple[str, str]]:
    return VALUESETS[comp["valueSet"]]["codes"]

def load_ambiguous():
    path = os.path.join(FHIR, "mimiciv-itemid-to-standard.conceptmap.json")
    if not os.path.isfile(path):
        return {}
    cm = json.load(open(path, encoding="utf-8"))
    byc = {}
    for g in cm.get("group", []):
        for el in g.get("element", []):
            for t in el.get("target", []):
                byc.setdefault(t["code"], set()).add(el.get("display", ""))
    return {c: sorted(n) for c, n in byc.items() if len(n) > 1}

AMBIGUOUS = load_ambiguous()

def ambiguous_codes(comp: Dict[str, Any]) -> List[str]:
    codes = {c for (_s, c) in codes_for(comp)}
    return ["%s both map to %s" % (" and ".join(AMBIGUOUS[c]), c)
            for c in sorted(codes & set(AMBIGUOUS))]

app = FastAPI(title="ICU Liberation Bundle CDS", version="0.1.0")

@app.get("/cds-services")
def discovery():
    services = []
    for comp in RULES["components"]:
        m = comp["min_per_24h"]
        desc = (("Checks whether %s assessment is documented at least %d times in 24 "
                 "hours, per SCCM adherence criteria." % (comp["name"].lower(), m))
                if m else
                ("Checks whether any %s activity is documented in the past 24 hours. "
                 "SCCM defines no numeric threshold for this component."
                 % comp["name"].lower()))
        services.append({
            "hook": "patient-view",
            "id": service_id(comp["id"]),
            "title": "ICU Liberation, component %s, %s" % (comp["id"], comp["name"]),
            "description": desc,
            "prefetch": {PREFETCH_KEY: ("Observation?patient={{context.patientId}}"
                                        "&_count=500&_sort=-date")},
        })
    return {"services": services}

def resource_codes(res: Dict[str, Any]) -> Set[Tuple[str, str]]:
    return {(c.get("system", ""), c["code"])
            for c in res.get("code", {}).get("coding", []) if c.get("code")}

def resource_time(res: Dict[str, Any]) -> Optional[datetime]:
    raw = (res.get("effectiveDateTime") or res.get("issued")
           or (res.get("effectivePeriod") or {}).get("start")
           or res.get("performedDateTime"))
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

COUNTABLE = {"Observation", "Procedure", "MedicationAdministration"}

def count_matching(bundle, wanted, now):
    cutoff = now - timedelta(hours=24)
    n = 0
    for entry in (bundle or {}).get("entry", []):
        res = entry.get("resource", {})
        if res.get("resourceType") not in COUNTABLE:
            continue
        if not (resource_codes(res) & wanted):
            continue
        t = resource_time(res)
        if t is None or t >= cutoff:
            n += 1
    return n

def build_card(comp, count):
    cid, need = comp["id"], comp["min_per_24h"]
    if need:
        if count >= need:
            indicator = "info"
            summary = ("Component %s met, %d of %d %s assessments in 24 hours"
                       % (cid, count, need, comp["name"].lower()))
        elif count == 0:
            indicator = "critical"
            summary = ("Component %s, no %s assessment documented in 24 hours"
                       % (cid, comp["name"].lower()))
        else:
            indicator = "warning"
            summary = ("Component %s, %d of %d %s assessments in 24 hours"
                       % (cid, count, need, comp["name"].lower()))
        criterion = ("SCCM adherence criteria require at least %d documented "
                     "assessments per 24 hours using %s." % (need, comp["instrument"]))
    else:
        if count > 0:
            indicator = "info"
            summary = ("Component %s, %d %s entr%s documented in 24 hours"
                       % (cid, count, comp["name"].lower(), "y" if count == 1 else "ies"))
        else:
            indicator = "warning"
            summary = ("Component %s, no %s documented in 24 hours"
                       % (cid, comp["name"].lower()))
        criterion = ("SCCM defines no numeric adherence threshold for this "
                     "component, so this card reports documentation only.")
    detail = ["**ICU Liberation Bundle, component %s, %s**" % (cid, comp["title"]),
              "", criterion, "",
              "Found **%d** matching record(s) in the last 24 hours." % count]
    if comp.get("significant"):
        detail += ["", "Clinical threshold, " + comp["significant"] + "."]
    amb = ambiguous_codes(comp)
    if amb:
        detail += ["", "*Caveat.* " + ". ".join(amb)
                   + ". A consumer working from codes alone cannot separate them, "
                     "so this count may be inflated."]
    return {"summary": summary[:139], "indicator": indicator,
            "detail": "\n".join(detail),
            "source": {"label": "ICU Liberation Bundle"}}

class HookRequest(BaseModel):
    hook: str
    hookInstance: str
    context: Dict[str, Any] = {}
    prefetch: Dict[str, Any] = {}
    fhirServer: Optional[str] = None
    fhirAuthorization: Optional[Dict[str, Any]] = None

@app.post("/cds-services/{sid}")
def invoke(sid: str, req: HookRequest):
    comp = next((c for c in RULES["components"] if service_id(c["id"]) == sid), None)
    if comp is None:
        return {"cards": []}
    bundle = req.prefetch.get(PREFETCH_KEY)
    if bundle is None:
        return {"cards": [{
            "summary": "ICU Liberation check could not run, no clinical data supplied",
            "indicator": "info",
            "detail": ("The service received no prefetched resources and no FHIR "
                       "server it could query, so it is reporting nothing rather "
                       "than guessing."),
            "source": {"label": "ICU Liberation Bundle"}}]}
    n = count_matching(bundle, codes_for(comp), datetime.now(timezone.utc))
    return {"cards": [build_card(comp, n)]}
