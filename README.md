# Health Cohort Builder

A Streamlit web tool for authoring a health data cohort definition directly, and
exporting it as a `requirement.yaml`. A researcher or analyst builds the cohort
logic in a structured form instead of writing prose or YAML by hand. The output
is a machine readable file that downstream tooling can consume.

Why it helps: a typed, structured form removes whole classes of error (criteria
lost in free text, or codes entered incorrectly), and it makes the cohort logic
(nested AND/OR sets and ordered exclusions) explicit.

## Design in one picture

The requirement mirrors how a cohort is built:

```
INCLUSION container   (the base population, built first)
    items combine with AND (INTERSECT, "all of") or OR (UNION, "any of"); may nest
EXCLUSIONS            (an ordered list, removed in turn)
```

Each group is a complete, standalone cohort. Leaf conditions are of three kinds:
demographic, codes (verbatim codes tied to a source dataset), and note (a
criterion that has no agreed code yet). See the worked output in
`examples/requirement.example.yaml` and the spec in `docs/SPEC.md`.

## Layout

* `app.py` : the Streamlit form.
* `requirement_schema.py` : single source of truth (schema, validation, import and export).
* `examples/requirement.example.yaml` : worked, annotated output.
* `docs/SPEC.md` : requirements spec.
* `scripts/shoot_ui.py` : autonomous screenshot harness (headless render to PNG).
* `tests/` : schema and Playwright interaction tests.
* `ui_shots/` : generated screenshots (gitignored).

## Run

```bash
pip install -r requirements.txt
python -m playwright install chromium     # for screenshots and tests only

streamlit run app.py                       # the app
python -m pytest tests/                     # schema and interaction tests
```

## Use

Build groups in the form: add conditions, add nested INTERSECT or UNION
subgroups, and add ordered exclusions. Use **Preview YAML** to review, **Download
YAML** to export, or **Load a requirement.yaml** to bring one back in to edit.
Use **Clone group** to start a similar cohort from a copy.
