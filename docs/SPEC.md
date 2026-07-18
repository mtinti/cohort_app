# Requirement Authoring Web Tool — Requirements Spec

> **Variant note:** this spec describes the full **SHARE/GoSHARE** design,
> including biobank **sample / event-anchored selection** and RDMP mapping. That
> is now a **UI feature flag on the single `main` codebase**: set
> `COHORT_ENABLE_SAMPLES=1` to *offer* the `sample` condition kind + biobank
> project type in the form. **The schema itself is flag-independent** — every
> kind and project type parses and validates identically everywhere, so a given
> `schema_version` means exactly one thing in every environment. Default (flag
> off) the form offers the **general health-data cohort builder** kinds
> (demographic / codes / note). Everything else (groups, INTERSECT/UNION
> containers, ordered exclusions, load / clone / preview) is shared by both.

**Status:** draft v2.3 (2026-07-18) — **schema v3**: v2 plus the `opcs[]`
(OPCS-4) code field and controlled code forms (see §5.4; registry v2 defines
span ranges, dot normalization and per-vocabulary allowed forms). Schema v2
(2026-07-15) added persistent `id`s,
one-schema-for-all-environments, draft-vs-strict loading, the **logical source
registry** (`sources.yaml` — `source` values are registry names, matching
semantics are registry-normative), the **`measure` kind** (value thresholds),
optional **`when` timing** on codes/measure leaves (absolute window and/or a
per-patient index-event **anchor** — the generalisation of §5.5), a **typed
`within`** (`{n, unit}`), a **sex enum** (any/female/male), and the optional
**`contract` header** (id/version/status/parties/`body_sha256` canonical body
hash, sealed via the app). Compilation artifacts live in `compiler/`
(site bindings, feasibility, SQL + RDMP emitters) — see `plan.md`.
**Decisions locked:** Streamlit (Python) · structured-form-only · download-YAML-only ·
each group **self-contained** (one group = one complete RDMP build) ·
inclusion **container** + **ordered** exclusions (researcher-ordered subtraction) ·
event-anchored **sample membership** (single anchor).

Worked, annotated output: **`examples/requirement.example.yaml`**.

---

## 1. Purpose & motivation

Today a researcher fills in a **Word feasibility form**; a SHARE analyst reads it
and an LLM ("Agent 1") must *extract* it into a structured `requirement` before
"Agent 2" can assemble the RDMP cohort (`build.script.yaml`).

This tool lets the **researcher author the structured requirement directly** in a
web form that emits a downloadable **YAML file** — the same contract Agent 2
consumes. The docx and the whole extraction stage are bypassed.

Why this is high-value (see `PROJECT-JOURNEY.md` in the pipeline repo — not in this repo):

- **Eliminates two proven bug classes at the source** — criteria lost in Word text
  boxes (30–60 % of some forms) and code/range mis-transcription. Typed structured
  fields remove both.
- **Removes extraction as an error stage.** The researcher *is* the extractor; the
  pipeline no longer inherits Agent-1's ~0.62 F1 ceiling.
- **Makes the hard cases first-class.** Multi-cohort (SHARE-2213) becomes explicit
  "add a group" actions, and **event-anchored temporal selection** (sample timed
  vs hospitalisation / prescription / GP diagnosis / lab result) becomes a typed
  field instead of prose a model must infer.

## 2. Users & primary flow

- **Primary user:** the researcher requesting a cohort (non-technical re: RDMP).
- **Secondary user:** the SHARE analyst capturing/cleaning a request.

Flow: open app → project metadata → **build one group at a time** (inclusion
container, then ordered exclusions) → add more groups as needed → review a live
YAML preview → **Download `requirement.yaml`** → hand to the cohort builder.

## 3. Design principle — mirror the CIC (the "link")

The requirement is structured to **mirror how a CIC is built**, so every block in
the form has a visible counterpart in the build. It is **not** a second RDMP
editor — it never exposes handles, SQL, set-handles, or index-table plumbing
(those remain the builder's job). It is just **similar enough to keep the link**:

```
Root container = EXCEPT
  child 1  = the INCLUSION container   (the base population, built first)
  child 2+ = EXCLUSION sets, SUBTRACTED in turn, in the order the researcher lists
```

| in the YAML | in the RDMP CIC |
|---|---|
| a group's `inclusion` (`op: AND`) | INTERSECT population container |
| a sub-container `op: OR` | UNION container |
| `exclusions: [...]` (ordered) | the root **EXCEPT** siblings, subtracted in order |
| `kind: codes` leaf (with `source`) | a cohort set / filter on that one catalogue |
| `kind: demographic` leaf | a filter on `SHARE_Demography` |
| `kind: sample` leaf | an index-date table (PIT) + `EXISTS(sample in window)` join |
| `kind: note` leaf | surfaced to the analyst; no auto-build |

## 4. Scope

**In scope (v1):** single-file **Streamlit** app run locally; a **structured form**
covering the whole schema (§5); **group-at-a-time** authoring with each group a
**self-contained** full build; nested **AND/OR containers**; **ordered exclusions**;
the **`sample_event`** index rule (single anchor); **basic client-side validation**
(§6); **live YAML preview** + **download**.

**Out of scope (v1)** — handled downstream or deferred:
- Deterministic **code expansion** (`scripts/expand_codes.py`, pipeline repo).
- **Catalogue/filter mapping** & **structural validation** (Agent 2 +
  `scripts/validate_build_script.py`, both pipeline repo).
- "Smart form" extras: manifest-backed autocomplete, live expansion preview,
  one-click "build cohort", docx import pre-fill (all → §11 future).
- Auth, persistence/DB, Jira integration, hosting/CI.

## 5. Output contract — the requirement YAML (schema)

The form output **must deserialize to the shape Agent 2 consumes**, and codes are
emitted **verbatim** (expansion happens downstream). Canonical worked file:
`examples/requirement.example.yaml`.

### 5.1 Top level

| field | type | notes |
|---|---|---|
| `project` | string | project title |
| `project_type` | enum `recruitment` \| `registry` \| `biobank` \| `other` | hints the builder's template family; the schema accepts all four everywhere (the UI flag only gates what the form offers) |
| `target_n` | string | free text, e.g. "15 per group (90 total)" |
| `ticket` | string (optional) | Jira key; names files / tags YAML only — **no Jira calls** |
| `schema_version` | int | currently `3` (v1/v2 files draft-load and upgrade; unknown versions are rejected by the gate) |
| `cohorts` | list of **Group** | one self-contained group per CIC build |

### 5.2 Group (self-contained = one full RDMP build)

| field | type | notes |
|---|---|---|
| `id` | string | **persistent id** — stable across load/edit/export; addresses the group in diffs, review comments and feasibility errors |
| `name` | string | group label; must be **unique** within the file (names one build) |
| `inclusion` | **Container** | the base-population container (built first) |
| `exclusions` | ordered list of **Member** | each subtracted in turn (root EXCEPT) |

### 5.3 Container

`{ id, op: AND | OR, label?: string, members: [ Member ] }` — `AND`→INTERSECT,
`OR`→UNION. Containers may nest (a member can be another container). Every
container and leaf carries a persistent `id` (as groups do).

### 5.4 Member = a Container **or** a leaf cohort set (`kind`)

**`kind: demographic`** — `source` (usually `SHARE_Demography`), `age_min`,
`age_max` (int|null), `sex`, `residence`, `simd` (strings), `label`.

**`kind: codes`** — `source` (a logical registry source), `label`, and the
relevant code lists **verbatim**: `icd[]`, `opcs[]`, `read[]`, `bnf[]`,
`drug_names[]` (only those that apply). Codes are structurally CONTROLLED
(no descriptions): each vocabulary defines allowed forms in `sources.yaml`.
ICD-10/OPCS-4 accept chapter (`F`), block range (`F00-F09`, cross-letter
`C00-D48` — ICD chapters cross letters), category (`F02`) and subcategory
(`F02.3`, the maximum depth); dots are presentational (matching strips them
on both sides).

**`kind: sample`** — `label`, plus a `sample_event` (see §5.5). Means "the person
has **≥1 biobank sample** positioned in time relative to the event." We count
people; the sample is never selected.

**`kind: note`** — `label`, `text`. A real criterion with no agreed code yet;
surfaced to the analyst, not auto-built.

### 5.5 `sample_event` (single anchor)

```
sample_event:
  event:
    type: hospitalisation | medicine | gp_data | lab_result
    occurrence: first | last          # default: first
    label: <human description>
    codes: [ ... ]                    # vocabulary follows `type` (see table)
  direction: before | after
  within: "<N units>"                 # optional; omit => any time in that direction
```

Per-event-type code vocabulary:

| `type` | data source | codes |
|---|---|---|
| `hospitalisation` | SMR admissions | ICD-10 |
| `medicine` | PIS prescribing | BNF (+ optional drug names) |
| `gp_data` | GP records | READ |
| `lab_result` | biochemistry/lab | **free text for now** (to be tightened) |

**Semantics:** the event's `occurrence` (default first) defines a per-patient
**index date**; the person is included iff they have ≥1 biobank sample with
`SampleDate` `direction` the index date (optionally within `within`).

## 6. Functional requirements (the form UI)

**F1 — Project section.** `project`, `project_type` (radio + helper text on the two
families), `target_n`, optional `ticket`.

**F2 — Group manager.** Build **one group at a time**; "➕ Add group" / "🗑 Remove" /
rename. Each group is independent and self-contained (no shared block). A read-out
reminds the user "this group = one RDMP build."

**F3 — Inclusion container editor (per group).** A recursive **container editor**:
choose `op` (AND/OR) and add members; a member is either a nested container or a
leaf cohort set (F5). Visual nesting indentation conveys INTERSECT/UNION structure.

**F4 — Exclusions editor (per group).** An **ordered list** of members (leaf or
container) with **reordering** (move up/down) — order is preserved in the YAML and
shown as "subtracted 1st, 2nd, …". Empty list allowed.

**F5 — Cohort-set leaf editor (reusable).** Pick `kind`
(demographic / codes / sample / note); render the right fields:
- *demographic*: age range, sex, residence, SIMD, source.
- *codes*: a `source` picker + verbatim code list editors (icd/read/bnf/drug_names;
  one code per line); format hints from `references/code-expansion.md` (pipeline repo).
- *sample*: the `sample_event` editor (F6).
- *note*: label + free text.

**F6 — `sample_event` editor.** `event.type` selector that **switches the code
field's vocabulary** (ICD/BNF/READ/free), `occurrence` (first/last), event `label`
+ `codes`; `direction` (before/after); optional `within` (number + unit).

**F7 — Live YAML preview** (read-only pane, updates as you edit).

**F8 — Download** `requirement.yaml` (`st.download_button`), named from `ticket`/
`project` (e.g. `Share-2213.requirement.yaml`).

## 7. Validation (basic, client-side only)

Shape and obvious mistakes — **not** semantics (semantics = downstream):
- Required: `project` non-empty; `project_type` chosen; each group has a `name` and
  a non-empty `inclusion`.
- Each leaf is internally consistent (a `codes` leaf has ≥1 code; a `sample` leaf
  has an event type + ≥1 event code unless `lab_result` free text; `age_min ≤
  age_max`).
- Light **format hints** (warnings) reusing the regexes/spec in
  `scripts/expand_codes.py` / `references/code-expansion.md` (pipeline repo) so form and expander
  agree on what's parseable.
- A container has ≥1 member; `op` is set.

**Not** validated here (deferred): code expansion correctness, catalogue/filter
existence, RDMP structural rules.

**Loading is two-mode (fail-closed for contracts):**
- **Draft load** (`from_contract`) — tolerant, for repairing work-in-progress
  files; every coercion (unknown kind kept visible as a note, wrapped
  inclusion, version mismatch) is **reported to the user**, never silent.
- **Strict gate** (`check_contract`) — required before a file counts as a
  contract (and, later, for compilation): rejects unsupported
  `schema_version`, unknown fields, unknown kinds/ops/project types, and
  missing or duplicate persistent `id`s. The app shows the gate result on
  every load.

## 8. Non-functional requirements

- **NFR1 — Local & light.** `streamlit` + `pyyaml`; `streamlit run app.py` from repo
  root. No DB/server.
- **NFR2 — No PII at rest.** Holds *criteria*, not patient data; nothing persisted
  server-side; output is a download.
- **NFR3 — Schema parity.** The form imports a single shared schema module
  (`requirement_schema.py` or `requirement.schema.json`); a test asserts the
  round-trip form-dict → YAML → loads → validates → is accepted by the pipeline.
- **NFR4 — Pipeline-ready.** A produced `requirement.yaml` runs through
  `expand_codes` + Agent 2 with no manual editing (acceptance §9).

## 9. Acceptance criteria

1. Re-authoring **SHARE-2213** as two self-contained groups (severe-DR; control)
   reproduces `examples/requirement.example.yaml`'s structure, and each group
   drives Agent 2 to a **validating** build (matching the proven
   `assemble_*_2213` path).
2. A **recruitment** single-group case (e.g. SHARE-2249) authored in the form
   assembles to a validating build with the expected catalogues/filters.
3. The emitted YAML loads via the **same** reader the pipeline uses and conforms
   to the schema module — verified by an automated round-trip/parity test.
4. Every schema field (§5) is authorable in the form, and every form field exists
   in the schema (coverage test).
5. Exclusion order in the form is preserved verbatim in the YAML.

## 10. Implied builder (Agent-2) changes — contract extensions to track

This schema extends what Agent 2 currently consumes; the builder/skill must learn:
- **Nested AND/OR containers** → INTERSECT/UNION container nesting (today's
  assembler mostly handles a flat inclusion INTERSECT + root EXCEPT).
- **Ordered `exclusions`** → EXCEPT siblings in the given order.
- **`source`-tagged `codes`** → apply each code set to the named catalogue (enables
  "same concept across SMR **or** GP" as a UNION).
- **`kind: sample` / `sample_event`** → the index-date pattern: derive a per-patient
  index date from the event (first/last occurrence of the coded event in its
  source), join the biobank sample catalogue, keep people with `EXISTS` a sample in
  the `direction`/`within` window. (New recipe; ties into the biobank-recipes gap.)
- **`kind: note`** → emit as a human-review TODO in the draft, never silently drop.

## 11. Deliverables

- `requirement_schema.py` (or `requirement.schema.json`) — single source of truth,
  imported by app **and** pipeline.
- `app.py` — the Streamlit form (F1–F8).
- Adapter note/script documenting `requirement.yaml` → `expand_codes` → Agent 2.
- `tests/` round-trip + schema-coverage tests.
- README: how to run, the schema, the handoff.

## 12. Open items / future (post-v1)

- "Smart form": manifest-backed catalogue/filter autocomplete, live ICD/BNF
  expansion preview, inline structural validation.
- One-click **"build cohort"** (feed YAML to the local assembler, show the draft).
- **docx import** to pre-fill the form (run current extractor as a first guess).
- Multi-anchor events ("sample **between** diagnosis and first prescription").
- Tighten `lab_result` vocabulary.
- Hosting/auth beyond local/internal use.
