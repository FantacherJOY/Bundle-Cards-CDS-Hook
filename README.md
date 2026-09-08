# ICU Liberation Bundle: CDS Hooks Service

Prospective clinical decision support (CDS) service for the ICU Liberation (ABCDEF) Bundle, implementing **HL7 CDS Hooks 2.0** and **FHIR R4**. 

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
| **`tools.py`** | Test and validation CLI (`test` for offline unit tests; `validate` for multi-database cohort checks). |
| **`extract.py`** | eICU nurseCharting extraction script converting flowsheets to native format. |
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


