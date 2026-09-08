# ICU Liberation Bundle, CDS Hooks service

All six ABCDEF bundle cards, running as a live clinical decision support
service. Each SCCM adherence rule becomes a CDS Hooks card that fires when a
clinician opens the patient.

Concept mappings and SCCM adherence thresholds come from a published analysis of
the ABCDEF bundle in MIMIC-IV. That work is the retrospective half. This
repository is the prospective half. Citation to be added.

## Run it

    pip install -r requirements.txt
    python tools.py test
    python tools.py validate
    uvicorn service:app --reload --port 8000

The tests need no server and no network, and they build their own patient data in
memory so they do not go stale. `python tests/make_sample.py` is optional and only
writes a fixed snapshot to poke the running service by hand with curl. Discovery is then at
http://localhost:8000/cds-services

## Against a real FHIR server

    docker run -p 8080:8080 hapiproject/hapi:latest

Generate patients with Synthea and load them, following
https://mitre.github.io/fhir-for-research/modules/synthea-test-server

Then run the CDS Hooks sandbox from https://github.com/cds-hooks/sandbox, point
it at your FHIR server, and add http://localhost:8000 as a discovery endpoint.
Your cards render inside a mock EHR patient view.

## Design

`bundle_cards.json` is the only place any code is written down. It carries all
34 concepts across the six components, each with its standard vocabulary code,
its OMOP concept ID, its OMOP CDM table, and the MIMIC-IV itemids used
to find it. Everything else is derived from it.

    fhir/                6 ValueSets and a ConceptMap, the definitions
    rules.json           the SCCM thresholds, which FHIR has no simple home for
    service.py           the CDS Hooks service, reads the files above
    tools.py             python tools.py test | validate
    
 The
first maps MIMIC-IV itemid to the standard code. The second maps standard code
to OMOP concept ID. Together they are the bridge between the retrospective
analysis and the live service, which is the part nobody usually builds.

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


