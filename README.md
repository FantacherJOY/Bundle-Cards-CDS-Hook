# ICU Liberation Bundle — CDS Hooks Service

Prospective clinical decision support (CDS) service for the ICU Liberation (ABCDEF) Bundle, implementing **HL7 CDS Hooks 2.0** and **FHIR R4**. 

This repository serves as the prospective companion to [vsubbian/Bundle-Cards](https://github.com/vsubbian/Bundle-Cards) and the published research:

> Islam MF, Douglas M, Mosier J, Subbian V. **Standardizing Data Elements for Implementation of ICU Liberation Bundle.** *Applied Clinical Informatics*, 2026;17(1):52-59. [doi:10.1055/a-2802-7458](https://doi.org/10.1055/a-2802-7458)

---

## 🏥 Clinical Overview

When an ICU clinician opens a patient's chart (`patient-view`), the service inspects the preceding 24 hours of charting and evaluates adherence to Society of Critical Care Medicine (SCCM) guidelines:

- **Component A (Pain):** Assessment documented at least 6 times / 24h (CPOT, NRS, BPS).
- **Component B (Breathing Trials):** Spontaneous Awakening/Breathing Trial (SAT/SBT) documentation.
- **Component C (Sedation):** Arousal/sedation assessment documented at least 6 times / 24h (RASS).
- **Component D (Delirium):** Delirium assessment documented at least 2 times / 24h (CAM-ICU).
- **Component E (Early Mobility):** Documentation of mobility or transfer assessments.
- **Component F (Family Engagement):** Documented family communication or meeting.

The service returns point-of-care decision cards indicating whether targets are **MET** or **MISSED**.

---

## 📁 Repository Structure

| File / Directory | Description |
|---|---|
| **`service.py`** | Live FastAPI CDS Hooks service providing Discovery (`GET /cds-services`) and Invocation (`POST /cds-services/{id}`). |
| **`rules.json`** | Machine-readable SCCM adherence thresholds and clinical scoring criteria. |
| **`fhir/*.valueset.json`** | 6 FHIR ValueSets defining standardized LOINC and SNOMED CT codes for each component. |
| **`fhir/*.conceptmap.json`** | FHIR ConceptMap translating local flowsheet/item IDs to standardized codes. |
| **`tools.py`** | Test and validation CLI (`test` for offline unit tests; `validate` for MIMIC-IV cohort checks). |
| **`requirements.txt`** | Python dependencies (`fastapi`, `uvicorn`, `pydantic`). |

---

## 🔌 Hospital EHR Interoperability

Different ICU systems (Epic flowsheets, Cerner, Philips, MIMIC) record data using internal proprietary IDs. Because this tool uses FHIR standards, the clinical decision logic is decoupled from local charting:

```
Hospital Flowsheet Code (Epic / Cerner)
             ↓   mapped by: fhir/*-to-standard.conceptmap.json
Standard Codes (LOINC / SNOMED)
             ↓   validated by: fhir/icu-liberation-[a-f].valueset.json
SCCM Adherence Evaluation (rules.json & service.py)
             ↓
Point-of-Care EHR Decision Support Card
```

To adapt this service to a new hospital, only a local ConceptMap JSON is needed; the adherence engine and alerting service remain untouched.

---

## 🚀 Quick Start

### 1. Installation
```bash
pip install -r requirements.txt
```

### 2. Run Offline Tests
Tests run in-memory with synthetic patient data (no server or network required):
```bash
python tools.py test
```

### 3. Run the Live Service
```bash
uvicorn service:app --reload --port 8000
```
- **Discovery endpoint:** `http://localhost:8000/cds-services`
- **Interactive documentation (Swagger UI):** `http://localhost:8000/docs`
- **CDS Hooks Sandbox:** Open [sandbox.cds-hooks.org](https://sandbox.cds-hooks.org), click **Add CDS Service**, and add `http://localhost:8000/cds-services`. Your cards will render directly inside the mock EHR view.

## Adherence rules implemented

| Component | Rule | Source |
|---|---|---|
| A, pain | at least 6 assessments per 24 hours | SCCM |
| B, breathing trials | documentation only | no numeric SCCM criterion |
| C, sedation | at least 6 arousal assessments per 24 hours | SCCM |
| D, delirium | at least 2 assessments per 24 hours | SCCM |
| E, early mobility | documentation only | no formal SCCM specification |
| F, family engagement | documentation only | no formal SCCM specification |

## Known issues in the mappings

All OMOP concepts below were checked in Athena on 2026-09-04 and every one is
Standard and Valid.

**Component B.** SAT failure and SBT stopped both carry SNOMED 407563006, which
OMOP 4253173 names "Treatment not tolerated", concept class Context-dependent,
domain Observation. Neither event can be identified from codes alone and
unrelated intolerance also matches.

**Component C.** RASS score and Goal RASS score both carry SNOMED 457441000124102,
OMOP 36684829, concept class Staging / Scales. That is the instrument, not the
score. The observable, SNOMED 1345050000, is non standard in OMOP and must not be
used as measurement_concept_id, so the value set carries it for matching only.

**No standard code.** Sedative medications and analgesic medications are RxNorm
classes rather than single codes. Mobilization plan has none. The CPOT elements
sit in the OMOP Extension vocabulary with no SNOMED or LOINC equivalent.

**Itemid 228300.** Listed in the source tables under CAM-ICU mental status change
and absent from the reference notebook. A `d_items` lookup confirms it is a real
chartevents item. It appears on 4,059 patient days across 1,450 patients, always
alongside another CAM-ICU itemid, so no reported figure changes. This repository
includes it.

## Checking it against real data

A service that only runs on synthetic patients proves the plumbing and nothing
else. `validate.py` closes that gap by computing every adherence
count twice for the same patient day. Once the way the reference
notebook does it, a groupby over itemids. Once by converting the same
rows into FHIR Observations and asking this service. Then it compares.

    python validate.py
    python validate.py --component D --verbose

The CSV is whatever the notebook already pulls, saved with `df.to_csv()`. Only
subject_id, itemid and charttime are needed.

Agreement means a live service would say the same thing about a patient that the
published retrospective analysis said. Disagreement is the useful output, and the
tool prints the offending patient days and the itemids involved.

**Result on MIMIC-IV, 2026-09-04.** Across a five stay export of 9,964 chartevents
rows the two paths agree on every patient day. Component A, 151 of 151. Component
C, 175 of 175. Component D, 145 of 145. No rows were dropped by the converter, so
the FHIR path saw exactly the rows the notebook path saw. This says the
prospective service introduces no error relative to the published retrospective
method. It does not independently confirm the published figures, which is a
separate question.

The conversion reads `fhir/mimiciv-itemid-to-standard.conceptmap.json` rather than
carrying its own copy of the mapping. Any itemid present in the data but missing
from that ConceptMap is collected and reported.

## Where this goes next

Fill in the RxNorm value sets for component C from Table A.4. Add a
`PlanDefinition` per component so the rules are FHIR native rather than Python.
Then point the whole service at Ottehr, which is FHIR native, for Aim 3.


