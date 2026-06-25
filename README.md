# Cohort Requirement Builder

A Streamlit web tool that lets a **researcher author a SHARE/GoSHARE cohort
requirement directly** — replacing the Word feasibility form *and* the LLM
extraction stage. It outputs a `requirement.yaml` that is the contract fed to the
cohort builder (the RDMP `build.script.yaml` assembler in the sibling `rdmp_agent`
project).

Why: a typed, structured form removes two proven failure modes of the
docx→extraction pipeline (criteria lost in Word text boxes; code/range
mis-transcription) and makes the hard cases — multiple cohorts, and
event-anchored sample selection — first-class fields instead of prose a model
must infer.

## Design in one picture

The requirement **mirrors how an RDMP CIC is built**, so every block has a visible
counterpart in the build (the "link"), without being a second RDMP editor:

```
Root container = EXCEPT
  child 1  = INCLUSION container   (base population, built first)   AND→INTERSECT, OR→UNION
  child 2+ = EXCLUSION sets        (subtracted in turn, in the order the researcher lists)
```

Each **group** is fully self-contained (= one complete RDMP build). See the
annotated, worked output in [`examples/requirement.example.yaml`](examples/requirement.example.yaml)
and the full spec in [`docs/SPEC.md`](docs/SPEC.md).

## Layout

| path | what |
|---|---|
| `app.py` | the Streamlit form (to build) |
| `requirement_schema.py` | single source of truth for the YAML schema (to build) |
| `docs/SPEC.md` | requirements spec (v2) |
| `examples/requirement.example.yaml` | worked, annotated output |
| `scripts/mockup.py` | static layout mockup (for the screenshot loop) |
| `scripts/shoot_ui.py` | autonomous screenshot harness (headless render → PNG) |
| `tests/` | schema/round-trip/coverage + Playwright interaction tests (to build) |
| `ui_shots/` | generated screenshots (gitignored) |

## Run

```bash
pip install -r requirements.txt
python -m playwright install chromium        # for screenshots/tests only

streamlit run app.py                          # the app (once built)
python scripts/shoot_ui.py scripts/mockup.py  # render a page headless → ui_shots/<name>.png
```

## Status

Spec settled (v2); screenshot dev-loop proven on the mockup. Next: build
`requirement_schema.py` + `app.py`, iterating via `scripts/shoot_ui.py`.
