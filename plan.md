# Plan: from cohort authoring tool to a portable cohort contract system

**Status:** proposal, revision 2 (incorporates external review) · 2026-07-15
**Scope note:** written generically — no organisation-specific examples. "Site" below
means any execution environment (safe haven / TRE / data provider) holding
similarly-shaped health data, typically split by region.

**Revision 2 changes (from review):** fail-closed contract gate (draft vs strict
loading); code-matching semantics moved out of site bindings into the
contract/registry; feature flag no longer changes the accepted schema (UI-only);
persistent criterion IDs kept in the export; compiler fails on `note` leaves by
default; real-requirement fixtures added as step 0; extraction spec referenced
from the header; a **Deferred hardening** section (§6) records what is
consciously postponed rather than missed.

---

## 1. Problem statement

Cohort requirements for clinical trials, studies, and recruitment are today
captured as free-form documents. Turning them into an executable query is a
manual, error-prone interpretation step, repeated per request and per site.

The goal is a **contract-based flow**:

1. Customer and organisation agree a cohort definition as a structured,
   machine-readable **contract** (YAML) — what to search and how.
2. A **deterministic compiler** (optionally assisted by an LLM only *upstream*,
   for drafting) turns the contract into an executable script — SQL, or a
   command script for a cohort platform such as RDMP.
3. The script runs **inside each site's** environment, respecting local
   data-collection specifics, with no model and no manual translation in the
   loop.
4. The contract itself is **general**: one contract, many sites, because the
   underlying data is the same (or similar) and only regionally split.

**Core invariant (added in rev 2):** the same approved contract must select the
same patients at every site that can execute it. Anything that can change *who
is in the cohort* is contract/registry semantics; only physical naming may vary
per site.

## 2. What exists today

**This repo (`cohort_app`)** is a Streamlit form where a researcher/analyst
authors a cohort definition and exports `requirement.yaml`:

- Schema (single source of truth, `requirement_schema.py`): a requirement holds
  N self-contained **groups**; each group = an **inclusion container**
  (AND=INTERSECT / OR=UNION, nestable) + an **ordered exclusions list**
  (subtracted in turn). Leaves: `demographic`, `codes` (verbatim code lists
  tagged with a `source`), `note` (criterion with no agreed code — explicit
  escape hatch).
- Round-trip (export → load → edit) works and is tested (unit + Playwright).
- Validation is shape-only; `source` is free text; several fields are free text
  (`within`, `sex`, `target_n`, code ranges).
- **Known defects to fix (confirmed by review):** loading is *fail-open* —
  unknown criterion kinds are silently coerced to notes, unsupported
  `schema_version` values are accepted, and the result validates clean (a
  contract's meaning can silently change on import). The
  `COHORT_ENABLE_SAMPLES` feature flag changes *what the schema accepts* at
  import time, so the same `schema_version` means different things in
  different environments. Internal node IDs are stripped on export, so
  criteria have no stable identity across versions.

**The downstream execution side (separate repo, RDMP proposals)** already has
the deterministic half proven:

- A cohort configuration can be **exported as a replayable command script**
  (`build.script.yaml`, an ordered `Commands:` list) and **rebuilt identically
  on another server** via CLI — everything that runs inside a site is
  deterministic platform code; no LLM ever runs inside a site.
- Exported scripts reference catalogues **by name**. Cross-site portability
  therefore currently relies on *naming convention only*: each site manually
  binds its tables, and **no artifact declares the per-site mapping**.
- The requirement input on that side is today a single line of free prose —
  there is **no structured requirement schema** in that pipeline.
- The platform also has a **native extraction layer** (what fields/datasets are
  released for a cohort) as a separate, already-governed step downstream of
  cohort selection — relevant to why extraction is referenced, not embedded,
  in this contract (§3.1, §6).
- An experimental LLM builder/verifier loop exists but treats model output as
  untrusted and funnels everything through the deterministic replay. (Its
  Python source currently exists only as compiled bytecode — it would need
  recovering or rewriting before being built upon.)

**The gap:** nothing connects the two. There is no contract semantics
(versioning/approval/provenance), no controlled source vocabulary, no per-site
mapping artifact, and no compiler from `requirement.yaml` to an executable
script.

## 3. Proposed design

Three artifacts + two programs. All execution-path code is deterministic.

```
                     ┌──────────────────────┐
 upstream free-form  │  LLM draft (OPTIONAL) │   ← only role for a model;
 request (doc/email) │  → draft contract     │     output always human-reviewed
                     └──────────┬───────────┘
                                ▼
   [1] requirement.yaml  ── authored/reviewed/APPROVED in this app
        (references only logical sources from [2])
                                │
   [2] sources.yaml  ── shared controlled vocabulary of logical sources
        + code-matching / expansion semantics (normative)
                                │
   [3] binding.<site>.yaml ── per-site PHYSICAL mapping only: logical source →
        local catalogue/table, columns (owned by the site)
                                │
   [4] validator ── draft-load vs STRICT GATE → registry conformance →
        per-site feasibility
                                │
   [5] compiler ── (contract + binding) → IR → emitter → executable script
                                │                ├─ SQL emitter (also the test harness)
                                ▼                └─ RDMP command-script emitter
        runs inside the site, deterministically
```

### 3.1 The contract (`requirement.yaml`) — evolve the existing schema

- **Header block** making it an agreement, not a form output:
  `contract: {id, version, status: draft|agreed, requested_by, approved_by,
  approved_on, body_sha256, references: {extraction_spec: <uri>}}`.
  The hash is computed over a **precisely defined canonical form** (canonical
  JSON: sorted keys, normalised unicode/whitespace) of the criteria body at
  approval, so any later edit is detectable. `references.extraction_spec`
  points to the (separately governed) document defining what is returned for
  the cohort — see §6 for why extraction is referenced, not embedded.
- **Persistent criterion IDs.** Every container and leaf keeps a stable ID in
  the exported YAML (today's internal `_id`s are stripped on export). IDs are
  preserved across load/edit/export so that feasibility errors, review
  comments, diffs between contract versions, and audit trails can address
  individual criteria. Nearly free to keep now; expensive to retrofit.
- **Logical sources only:** `source` becomes an enum drawn from the source
  registry, rendered as a dropdown in the form. No physical names in the
  contract, ever.
- **Structured everywhere except `note`:** typed time windows
  (`{n, unit}`), typed demographics, code ranges as `{from, to}`. Rule: *free
  text may exist only in `note` leaves.* A contract is **deterministically
  compilable iff it contains no notes** — a checkable property surfaced in the
  UI and enforced by the compiler (§3.5).
- **One schema for all environments.** Feature flags (e.g.
  `COHORT_ENABLE_SAMPLES`) affect only what the *UI offers*, never what the
  schema accepts or how a file is parsed. A given `schema_version` means
  exactly one thing everywhere.
- **Two expressiveness additions** (near-universal in eligibility criteria):
  1. **Temporal anchoring**, generalised: study period / lookback windows, and
     criteria positioned relative to a per-patient index event
     (first/last occurrence of a coded event; direction; optional window).
     A restricted version of this already exists behind a feature flag; it
     should become a first-class, general primitive.
  2. **Value predicates** for threshold criteria:
     `{measure, op, value, unit}` (e.g. a lab measure ≥ a threshold).

### 3.2 The source registry (`sources.yaml`)

One shared, versioned file defining the controlled vocabulary of **logical
sources** (order of ~6–10 entries): stable name, description, which criterion
kinds it supports (codes / demographic / measure), and which code vocabularies
are legal on it (vocabulary list must be extensible — not hardcoded to a fixed
set of field names). The form's dropdowns render from it; validation checks
contracts against it. It is the semantic anchor of the whole system.

**The registry is normative for meaning (rev 2).** Anything that changes cohort
membership is defined here (or in the contract), never per site: code-matching
mode (prefix vs exact), how code ranges expand to concrete codes, date-bound
inclusivity, null handling, unit conventions for measures. Two sites executing
the same contract must be running the same semantics by construction.

### 3.3 The binding manifest (`binding.<site>.yaml`)

One small file **per site, owned by that site**, written once and reused for
every contract: for each logical source it supports — local catalogue/table
name, patient-identifier column, date column, code column per vocabulary,
measure mappings. **Physical mapping only (rev 2):** a binding implements the
registry's semantics or declares a source/vocabulary unsupported; it can never
alter matching or expansion behaviour. Ships with its own JSON Schema so a site
can validate its binding independently of any contract. This artifact is what
makes "same data, region split" a declared, testable fact instead of a naming
convention.

### 3.4 The validator — draft mode vs the strict gate

Loading has **two explicit modes** (rev 2; today's single tolerant path is
fail-open and can silently change a contract's meaning on import):

- **Draft load (editor mode):** tolerant, for repairing work-in-progress —
  but every coercion (unknown kind, missing field, out-of-range value) is
  loudly reported in the UI, never silent.
- **Strict gate (contract mode):** required for approval and for compilation.
  Rejects unsupported `schema_version`, unknown kinds, unknown fields; never
  coerces; a file that fails the gate cannot be marked `agreed` or compiled.

On top of the gate, three static levels (no data access):

1. **Shape** — today's `validate()`, tightened per §3.1.
2. **Registry conformance** — every `source` exists; every vocabulary legal
   for its source; structured-field constraints hold.
3. **Site feasibility** — given a binding manifest: *can site X execute
   contract Y?* → yes/no + the list of unsupported criteria, addressed by
   criterion ID. Runs anywhere, touches no data.

Also: export the schema as **`requirement.schema.json`** so non-Python
consumers (e.g. the C# platform side) validate the identical contract.

### 3.5 The compiler

`compile(contract, binding) → executable script`, as a small deterministic
package. Intermediate representation (IR) = a set-algebra tree
(INTERSECT/UNION/EXCEPT over typed predicates), then pluggable emitters:

- **SQL emitter first** — it is both the second backend and the test harness:
  CI compiles fixture contracts against a fixture binding, runs the SQL on a
  synthetic in-memory dataset, and asserts the resulting cohort.
- **Platform command-script emitter second** (RDMP `Commands:` list). The
  contract's container structure maps 1:1 onto INTERSECT/UNION/root-EXCEPT,
  so this translation is mechanical.
- **Fail-closed (rev 2):** compilation *fails* if the contract contains `note`
  leaves, failed the strict gate, or contains any node the compiler/binding
  cannot prove it supports. An explicit `--draft` flag may emit annotated
  output for discussion, unmistakably labelled non-executable. No TODO markers
  in runnable output, ever.
- **Provenance in output:** the emitted script embeds the contract id/version/
  hash and the registry and binding versions it was compiled against.

The IR starts deliberately minimal (patient-level set algebra + code/
demographic predicates) and **grows only when a schema primitive lands** —
each expressiveness addition (temporal anchoring, value predicates, counts…)
arrives together with its IR node, compilation rule, and test. Designing the
full event-relational algebra up front is deferred (§6).

### 3.6 Trust boundary (explicit)

The **only** place a model may appear is upstream: interpreting a free-form
request into a *draft* contract, which a human reviews and approves **in this
app** (the existing load-YAML flow already supports review/repair of drafted
contracts — in draft mode, per §3.4). After approval: strict gate → compiler →
in-site execution, all deterministic and reproducible.

## 4. Implementation order

| # | Step | Where | Size | Value |
|---|------|-------|------|-------|
| 0 | Collect 2–3 representative real requirements as fixture files; define the deliberately narrow executable subset they need | this repo | S | keeps every schema decision honest (review suggestion, adopted) |
| 1 | Fail-closed foundations: draft-vs-strict loading, one-schema-for-all-environments (flag → UI-only), persistent criterion IDs in export | this repo | S | fixes the confirmed fail-open defects before anything is built on the format |
| 2 | Source registry (incl. normative matching/expansion semantics) + schema tightening (dropdown sources, typed `within`/demographics, note-only free text) | this repo | S | kills free-text drift; nails down the semantics sites must share |
| 3 | Contract header + canonical-JSON body hash + `requirement.schema.json` export | this repo | S | the artifact becomes a contract |
| 4 | Binding-manifest schema (physical-only) + feasibility checker | this repo (`compiler/` pkg start) | M | first cross-site value, zero execution dependency |
| 5 | Compiler: minimal IR + SQL emitter, fail-closed, CI harness on synthetic data; then platform emitter | `compiler/` pkg | M–L | end-to-end path proven on the step-0 fixtures |
| 6 | Temporal anchoring + value predicates (schema + form + IR + compiler + tests together, one primitive at a time) | both | L | biggest expressiveness lift; each addition lands with its compilation rule |

Steps 0–3 are independent of any execution backend and immediately useful.
4–5 share `requirement_schema.py`; split into a separate repo only if
ownership diverges.

Housekeeping alongside step 1: fix dangling spec references (files cited in
`docs/SPEC.md` that don't exist in-repo), require unique group names (they
become build names downstream), fix the cross-variant `project_type` mapping
bug on load. New tests to add with step 1: unsupported schema version is
rejected at the gate, unknown kind is rejected at the gate (and *reported* in
draft mode), criterion IDs survive export→load→export.

## 5. Alternatives considered

- **Adopt OHDSI Circe / OMOP cohort definitions wholesale.** Circe already
  solved index events, windows, thresholds. Rejected as the primary format:
  heavyweight, not human-readable by both parties to a contract, and assumes
  an OMOP CDM the target sites don't (yet) run. Mitigation: design the
  temporal/threshold extensions so they *map* to Circe concepts, keeping a
  future OMOP emitter open.
- **LLM compiles the contract per-site (no binding manifest).** Rejected:
  reintroduces non-determinism at exactly the step that must be auditable and
  reproducible inside a site; the downstream pipeline's own prototype treats
  model output as untrusted for this reason.
- **Physical catalogue names in the contract.** Rejected: breaks generality
  across sites and leaks site internals into a customer-facing agreement.
- **Semantics (code matching, expansion) in the site binding.** Rejected after
  review: it would let two sites select different cohorts from the same
  contract. Semantics are contract/registry-owned (§3.2); bindings are
  physical only.
- **Embed a full extraction/outputs schema in the contract now.** Rejected for
  the prototype: the target platform already has a separate, governed
  extraction layer downstream of cohort selection, and the cohort path is the
  unproven part. The contract *references* its extraction spec (§3.1); a
  first-class outputs module is deferred hardening (§6).
- **JSON Schema as the only source of truth (drop the Python module).**
  Deferred: the Python module also carries factories/round-trip logic the app
  needs; generate the JSON Schema *from* it instead.

## 6. Deferred hardening — consciously postponed, not missed

Raised in external review; agreed in principle, out of scope for the
prototype. Recorded here so the cut line is explicit:

1. **Full extraction/outputs specification** (row grain, fields and logical
   types, dedup/aggregation/linkage rules, output format, disclosure/
   pseudonymisation constraints, consent/contactability). For now the contract
   carries a `references.extraction_spec` pointer and the platform's existing
   extraction layer governs release. Becomes in-scope once the cohort path is
   proven on real requirements.
2. **Signed, detached approvals.** A body hash in a mutable file detects
   accidental drift, not adversarial edits (whoever edits the body can re-hash
   and re-set `approved_by`). Production needs a detached approval record /
   signed attestation / immutable workflow record covering the contract *and*
   its dependency versions. Prototype keeps: canonical hash + approval fields.
3. **Dependency digest pinning** (contract pins digests of registry, binding,
   compiler). Prototype keeps the lighter form: the *compiled output* records
   the versions it was built from (§3.5 provenance).
4. **Event-relational IR** (correlated events, sequences, counts, observation
   periods, multiple anchors, explicit row grain). The IR grows primitive-by-
   primitive with the schema (§3.5); the general algebra is designed when the
   primitives demand it.
5. **Review tooling suite**: generated plain-language contract view,
   criterion-level semantic diffs between versions, example-patient
   include/exclude scenarios, AI suggestions as provenance-carrying proposed
   patches. Persistent criterion IDs (step 1) are the enabling substrate and
   are *not* deferred.
6. **Standalone versioned contract package** (strict discriminated models,
   separate from UI factories, consumed by app + CLI + compiler). Revisit when
   the compiler package is split out; until then the single schema module +
   generated JSON Schema suffice.
7. **Formal schema migrations** between contract versions. Until v2 exists,
   the strict gate simply rejects unknown versions.

## 7. Risks / open questions (input wanted)

1. **Registry governance** — who owns `sources.yaml` (now including the
   normative matching/expansion semantics) and approves changes? A wrong
   abstraction here propagates everywhere.
2. **How similar is "similar"?** The design assumes sites differ in naming/
   columns, not in semantics. If a site's data model diverges structurally
   (e.g. no per-event coding), a physical binding cannot paper over it —
   feasibility checking will (correctly) fail. Is that acceptable?
3. **Vocabulary strategy** — contracts should support modern vocabularies
   (e.g. SNOMED CT, dm+d, OPCS-4) alongside legacy ones per source. Range
   expansion is registry-defined (§3.2); does the *expansion step* run in the
   compiler or as a shared pre-step producing pinned concrete code lists?
4. **Extraction spec granularity** — is a referenced external document (§3.1)
   sufficient for the agreement story short-term, or do approvers need at
   least a coarse `outputs:` summary (grain + dataset list) inside the
   contract before §6.1 lands?
5. **Downstream prototype source** — the existing LLM builder/verifier
   prototype survives only as bytecode; rewrite is assumed rather than
   recovery. Confirm nothing else depends on it.

## 8. Success criteria

- One approved contract + two different site bindings compile to two scripts
  that produce the same cohort on identically-seeded synthetic data — with
  matching semantics guaranteed by the registry, not by site convention.
- The step-0 fixture requirements (real, representative) round-trip through
  form → strict gate → compiler → synthetic execution.
- A file with an unsupported schema version or unknown criterion kind is
  rejected by the strict gate; in draft mode every coercion is visibly
  reported (regression tests for the confirmed fail-open defects).
- "Deterministically compilable" (no `note` leaves) is machine-checked,
  visible in the authoring UI, and enforced by the compiler (no runnable
  output from a contract containing notes).
- Feasibility check answers "can site X run contract Y?" with a
  criterion-ID-level diff, statically.
- A contract edited after approval is detectable via the canonical body hash.
- Every schema field is authorable in the form, validated by the shared
  schema, and covered by a compilation rule + test (no silently-dropped
  criteria anywhere in the path).
