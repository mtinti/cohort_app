# Cohort Requirement Builder

A Streamlit web tool for authoring a **health-data cohort definition** directly,
and exporting it as a `requirement.yaml`. A researcher (or analyst) builds the
cohort logic in a structured form instead of writing prose or YAML by hand; the
output is a machine-readable contract that downstream tooling can consume.

Why: a typed, structured form removes whole classes of error (criteria lost in
free text, mis-transcribed codes) and makes the cohort logic — nested AND/OR
sets and ordered exclusions — explicit.

## Variants (one codebase, one feature flag)

Default is the **general health-data cohort builder**. Set
`COHORT_ENABLE_SAMPLES=1` to enable the **SHARE/GoSHARE variant**, which adds a
`sample` condition kind (biobank sample / event-anchored selection — "≥1 sample
before/after a hospitalisation / prescription / diagnosis index date") and the
biobank project type.

```bash
streamlit run app.py                            # general builder
COHORT_ENABLE_SAMPLES=1 streamlit run app.py    # SHARE/GoSHARE variant
```

A general-mode session can still **load** a SHARE-authored YAML — sample
conditions appear as read-only notes; enable the flag to edit them.
(The `share_cohort_builder` branch is retained only as the archive tag
`archive/share_cohort_builder`; all development is on `main`.)

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
