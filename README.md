# Cohort Requirement Builder

A Streamlit web tool for authoring a **health-data cohort definition** directly,
and exporting it as a `requirement.yaml`. A researcher (or analyst) builds the
cohort logic in a structured form instead of writing prose or YAML by hand; the
output is a machine-readable contract that downstream tooling can consume.

Why: a typed, structured form removes whole classes of error (criteria lost in
free text, mis-transcribed codes) and makes the cohort logic — nested AND/OR
sets and ordered exclusions — explicit.

## Branches

- **`main`** — general cohort builder for health data (this branch).
- **`share_cohort_builder`** — the SHARE/GoSHARE variant, which additionally
  supports **biobank sample / event-anchored selection** ("has ≥1 sample
  before/after a hospitalisation / prescription / diagnosis index date") and
  maps onto the RDMP cohort-build pipeline.

## Design in one picture

The requirement mirrors how a cohort is built:

```
INCLUSION container  (base population, built first)   op: AND→INTERSECT (all of) / OR→UNION (any of)
EXCLUSIONS           (an ordered list, removed in turn)
```

Each **group** is fully self-contained (one complete cohort). Leaf conditions are
of three kinds: **demographic**, **codes** (verbatim codes tied to a `source`
dataset), and **note** (a criterion with no agreed code yet). See the worked
output in [`examples/requirement.example.yaml`](examples/requirement.example.yaml)
and the spec in [`docs/SPEC.md`](docs/SPEC.md).

## Layout

| path | what |
|---|---|
| `app.py` | the Streamlit form |
| `requirement_schema.py` | single source of truth: schema, validate, to/from contract |
| `examples/requirement.example.yaml` | worked, annotated output |
| `docs/SPEC.md` | requirements spec |
| `scripts/shoot_ui.py` | autonomous screenshot harness (headless render → PNG) |
| `tests/` | schema + Playwright interaction tests |
| `ui_shots/` | generated screenshots (gitignored) |

## Run

```bash
pip install -r requirements.txt
python -m playwright install chromium        # for screenshots/tests only

streamlit run app.py                          # the app
python -m pytest tests/                        # schema + interaction tests
python scripts/shoot_ui.py app.py --name shot  # render headless → ui_shots/shot.png
```

## Use

Build groups in the form (add conditions / nested INTERSECT-UNION sub-groups /
ordered exclusions), **👁 Preview YAML**, **⬇ Download YAML**, or **📁 Load** a
previously-saved `requirement.yaml` back in to edit. **⧉ Clone** a group to start
a similar cohort from a copy.
