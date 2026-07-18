"""Single source of truth for the cohort requirement schema (v2).

Imported by the Streamlit app, the compiler package and the tests, so they can
never drift. Holds:
  * the controlled vocabularies (project types, ops, kinds, event types …),
  * node factories (new_* — each carries an internal `_id` for the UI tree),
  * to_contract(req)  -> a clean dict ready to YAML-dump (persistent `id` per
                         group/container/leaf; internal `_id`/flags stripped),
  * from_contract()   -> DRAFT load: tolerant, but reports every coercion,
  * check_contract()  -> STRICT GATE: fail-closed check on a raw contract dict
                         (approval / compilation require a clean pass),
  * body_hash/seal/hash_status -> contract header hashing (canonical JSON),
  * json_schema()     -> the same contract as a JSON Schema document,
  * validate(req)     -> a list of human-readable problems (basic shape checks),
  * build_example()   -> the worked two-group example (mirrors examples/*.yaml).

Design (see docs/SPEC.md and plan.md): each GROUP is self-contained = one RDMP
build. inclusion is a CONTAINER (AND=INTERSECT / OR=UNION) built first;
exclusions are an ORDERED list subtracted in turn (root EXCEPT). Leaves are
cohort sets of kind demographic / codes / measure / sample / note.

Schema v2 (over v1): persistent ids; logical sources from the registry
(sources.yaml); `measure` kind (value thresholds); optional `when` timing on
codes/measure leaves (absolute window and/or per-patient index-event anchor);
typed `within` ({n, unit}); sex enum (any/female/male, was free text);
optional `contract` header (id/version/status/parties/body_sha256).
Free text may exist ONLY in `note` leaves (and labels/descriptions).

ONE SCHEMA FOR ALL ENVIRONMENTS: the schema always accepts every kind and
project type — a given schema_version means exactly one thing everywhere.
The env flag COHORT_ENABLE_SAMPLES=1 only widens what the UI OFFERS
(UI_KINDS / UI_PROJECT_TYPES: adds the `sample` kind and `biobank` type to the
authoring menus); it never changes what parses or validates.
"""
import hashlib
import json
import os
import re
import uuid

import registry as R

ENABLE_SAMPLES = os.environ.get("COHORT_ENABLE_SAMPLES", "").lower() in ("1", "true", "yes", "on")

OPS = ["AND", "OR"]
OP_NAME = {"AND": "INTERSECT (all of)", "OR": "UNION (any of)"}   # UI vocabulary
# Normative vocabularies (what the schema ACCEPTS — identical everywhere).
KINDS = ["demographic", "codes", "measure", "sample", "note"]
PROJECT_TYPES = ["recruitment", "registry", "biobank", "other"]
SEXES = ["any", "female", "male"]
CMP_OPS = ["<", "<=", ">", ">=", "=", "!="]
# What the authoring UI OFFERS (feature-flag gated; a superset never parses
# differently, the flag only surfaces extra choices in the form).
UI_KINDS = (["demographic", "codes", "measure", "sample", "note"] if ENABLE_SAMPLES
            else ["demographic", "codes", "measure", "note"])
UI_PROJECT_TYPES = (["recruitment", "biobank"] if ENABLE_SAMPLES
                    else ["recruitment", "registry", "other"])

# Sample / event-anchored selection (kind: sample).
EVENT_TYPES = ["hospitalisation", "medicine", "gp_data", "lab_result"]
EVENT_VOCAB = {"hospitalisation": "ICD-10", "medicine": "BNF",
               "gp_data": "READ", "lab_result": "free text"}
OCCURRENCE = ["first", "last"]
DIRECTION = ["before", "after"]
WITHIN_UNITS = ["days", "weeks", "months", "years"]
CONTRACT_STATUSES = ["draft", "agreed"]
# v3 (2026-07-18): adds the `opcs` code field (OPCS-4). A v2 consumer would
# reject `opcs` as an unknown field, so accepting it under the same version
# id would make "valid v2" deployment-dependent — hence the bump. Migration:
# ONLY the versions below draft-load with an upgrade to the current version
# (every coercion reported; re-seal after review). Unknown/future versions
# load as drafts but KEEP their version, so the gate keeps rejecting them.
SCHEMA_VERSION = 3
MIGRATABLE_VERSIONS = {1, 2}


def _int_version(sv):
    """Canonical integer schema version, or None if malformed.

    JSON's data model has a single number type, so the generated JSON Schema
    cannot distinguish 3 from 3.0 — mathematically integral numbers are
    therefore accepted and canonicalized (validator consistency). Bools are
    NOT numbers here (YAML true must never read as version 1), and neither
    are strings, lists or mappings.
    """
    if isinstance(sv, bool) or not isinstance(sv, (int, float)):
        return None
    return int(sv) if float(sv).is_integer() else None
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEMOG_SRC = "demographics"


def _id():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Node factories (UI-side nodes carry `_id`; exported as persistent `id`).
# ---------------------------------------------------------------------------
def new_container(op="AND", label="", members=None):
    return {"_id": _id(), "node": "container", "op": op, "label": label,
            "members": members if members is not None else []}


def new_demographic(label="", source=_DEMOG_SRC, age_min=None, age_max=None,
                    sex="any", residence="", simd=""):
    return {"_id": _id(), "node": "leaf", "kind": "demographic", "label": label,
            "source": source, "age_min": age_min, "age_max": age_max,
            "sex": sex, "residence": residence, "simd": simd}


def new_codes(label="", source=None, *, icd=None, opcs=None, read=None, bnf=None,
              drug_names=None, when=None):
    # vocabulary args are KEYWORD-ONLY: inserting a new vocabulary must never
    # silently shift an existing positional caller's codes into another field
    if source is None:
        source = R.sources_for("codes")[0]
    return {"_id": _id(), "node": "leaf", "kind": "codes", "label": label, "source": source,
            "icd": icd or [], "opcs": opcs or [], "read": read or [], "bnf": bnf or [],
            "drug_names": drug_names or [], "when": when}


def new_measure(label="", source=None, measure=None, op=">=", value=None, unit="",
                when=None):
    if source is None:
        source = (R.sources_for("measure") or [""])[0]
    if measure is None:
        measure = (R.measures_for(source) or [""])[0]
    return {"_id": _id(), "node": "leaf", "kind": "measure", "label": label,
            "source": source, "measure": measure, "op": op, "value": value,
            "unit": unit, "when": when}


def new_sample(label="", event_type="gp_data", occurrence="first", event_label="",
               codes=None, direction="before", within_n=None, within_unit="months"):
    # "person has >=1 sample positioned in time vs an index event"
    return {"_id": _id(), "node": "leaf", "kind": "sample", "label": label,
            "sample_event": {
                "event": {"type": event_type, "occurrence": occurrence,
                          "label": event_label, "codes": codes or []},
                "direction": direction,
                "within": {"n": within_n, "unit": within_unit}}}


def new_note(label="", text=""):
    return {"_id": _id(), "node": "leaf", "kind": "note", "label": label, "text": text}


def new_leaf(kind, label=""):
    return {"demographic": new_demographic, "codes": new_codes, "measure": new_measure,
            "sample": new_sample, "note": new_note}[kind](label=label)


def new_group(name="New group"):
    return {"_id": _id(), "name": name, "inclusion": new_container("AND"), "exclusions": []}


def _regen_ids(node):
    """Assign fresh _ids to a node and everything under it (for cloning)."""
    node["_id"] = _id()
    if node.get("node") == "container":
        for m in node.get("members", []):
            _regen_ids(m)


def clone_group(g):
    """Deep copy a group with brand-new _ids (so the tree stays addressable)."""
    import copy
    ng = copy.deepcopy(g)
    ng["_id"] = _id()
    _regen_ids(ng["inclusion"])
    for m in ng["exclusions"]:
        _regen_ids(m)
    ng["name"] = (g.get("name", "Group") + " (copy)")
    return ng


def new_requirement():
    return {"project": "", "project_type": "recruitment", "target_n": "", "ticket": "",
            "contract": None,
            "schema_version": SCHEMA_VERSION, "cohorts": [new_group("Group 1")]}


# ---------------------------------------------------------------------------
# Export: UI tree -> clean contract dict. The internal `_id` is exported as a
# PERSISTENT `id` (so criteria stay addressable across versions — for review
# comments, diffs, feasibility errors); other internal flags/empties are
# stripped.
# ---------------------------------------------------------------------------
def _clean_when(w):
    if not isinstance(w, dict):
        return None
    out = {}
    win = w.get("window") or {}
    win = {k: v for k, v in win.items() if k in ("from", "to") and v}
    if win:
        out["window"] = win
    a = w.get("anchor")
    if isinstance(a, dict) and a.get("event"):
        ev = a["event"]
        event = {"source": ev.get("source", ""), "vocab": ev.get("vocab", ""),
                 "codes": list(ev.get("codes", [])),
                 "occurrence": ev.get("occurrence", "first")}
        if ev.get("label"):
            event["label"] = ev["label"]
        anchor = {"event": event, "direction": a.get("direction", "before")}
        wi = a.get("within") or {}
        if wi.get("n") is not None:
            anchor["within"] = {"n": wi["n"], "unit": wi.get("unit", "months")}
        out["anchor"] = anchor
    return out or None


def _clean(n):
    if n.get("node") == "container":
        out = {"id": n["_id"], "op": n["op"]}
        if n.get("label"):
            out["label"] = n["label"]
        out["members"] = [_clean(m) for m in n.get("members", [])]
        return out
    k = n["kind"]
    out = {"id": n["_id"], "kind": k}
    if n.get("label"):
        out["label"] = n["label"]
    if k == "demographic":
        if n.get("source"):
            out["source"] = n["source"]
        for f in ("age_min", "age_max"):
            if n.get(f) is not None:
                out[f] = n[f]
        if n.get("sex") and n["sex"] != "any":
            out["sex"] = n["sex"]
        for f in ("residence", "simd"):
            if n.get(f):
                out[f] = n[f]
    elif k == "codes":
        if n.get("source"):
            out["source"] = n["source"]
        for f in ("icd", "opcs", "read", "bnf", "drug_names"):
            if n.get(f):
                out[f] = list(n[f])
        w = _clean_when(n.get("when"))
        if w:
            out["when"] = w
    elif k == "measure":
        for f in ("source", "measure", "op"):
            if n.get(f):
                out[f] = n[f]
        if n.get("value") is not None:
            out["value"] = n["value"]
        if n.get("unit"):
            out["unit"] = n["unit"]
        w = _clean_when(n.get("when"))
        if w:
            out["when"] = w
    elif k == "sample":
        ev = n["sample_event"]["event"]
        event = {"type": ev["type"], "occurrence": ev["occurrence"]}
        if ev.get("label"):
            event["label"] = ev["label"]
        event["codes"] = list(ev.get("codes", []))
        se = {"event": event, "direction": n["sample_event"]["direction"]}
        wi = n["sample_event"].get("within") or {}
        if isinstance(wi, dict) and wi.get("n") is not None:
            se["within"] = {"n": wi["n"], "unit": wi.get("unit", "months")}
        out["sample_event"] = se
    elif k == "note":
        out["text"] = n.get("text", "")
    return out


def to_contract(req):
    out = {}
    if req.get("contract"):
        out["contract"] = dict(req["contract"])
    out.update({"project": req.get("project", ""),
                "project_type": req.get("project_type", ""),
                "target_n": req.get("target_n", ""),
                "schema_version": req.get("schema_version", SCHEMA_VERSION)})
    if req.get("ticket"):
        out["ticket"] = req["ticket"]
    out["cohorts"] = [{"id": g["_id"], "name": g.get("name", ""),
                       "inclusion": _clean(g["inclusion"]),
                       "exclusions": [_clean(m) for m in g.get("exclusions", [])]}
                      for g in req.get("cohorts", [])]
    return out


# ---------------------------------------------------------------------------
# Contract header hashing — canonical JSON of the BODY (everything except the
# `contract` block), so an edit after approval is detectable. Canonical form:
# sorted keys, compact separators, ensure_ascii (defined once, here).
# ---------------------------------------------------------------------------
def body_hash(contract_dict):
    body = {k: v for k, v in (contract_dict or {}).items() if k != "contract"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def seal(req, approved_by=""):
    """Mark the requirement's contract header agreed + store the body hash."""
    import datetime
    hdr = dict(req.get("contract") or {})
    hdr.setdefault("id", _id())
    hdr["version"] = int(hdr.get("version") or 0) + 1
    hdr["status"] = "agreed"
    hdr["approved_on"] = datetime.date.today().isoformat()
    if approved_by:
        hdr["approved_by"] = approved_by
    req["contract"] = hdr
    hdr["body_sha256"] = body_hash(to_contract(req))
    return hdr


def hash_status(contract_dict):
    """'ok' | 'changed' | None (no sealed header)."""
    hdr = (contract_dict or {}).get("contract") or {}
    if not hdr.get("body_sha256"):
        return None
    return "ok" if body_hash(contract_dict) == hdr["body_sha256"] else "changed"


# ---------------------------------------------------------------------------
# Import (DRAFT load): tolerant, but every coercion is reported via `issues`.
# ---------------------------------------------------------------------------
def _keep_id(node, d):
    """Preserve a contract `id` on the rebuilt UI node (persistent identity)."""
    if isinstance(d, dict) and d.get("id"):
        node["_id"] = str(d["id"])
    return node


def _load_when(d, rec, where):
    w = d.get("when")
    if not isinstance(w, dict):
        if w is not None:
            rec(f"{where}: unparseable `when` dropped")
        return None
    out = {"window": dict(w.get("window") or {}), "anchor": None}
    a = w.get("anchor")
    if isinstance(a, dict):
        ev = a.get("event") or {}
        wi = a.get("within") or {}
        if isinstance(wi, str):                     # legacy "6 months"
            wi = _parse_legacy_within(wi, rec, where)
        out["anchor"] = {"event": {"source": ev.get("source", ""),
                                   "vocab": ev.get("vocab", ""),
                                   "codes": list(ev.get("codes") or []),
                                   "occurrence": ev.get("occurrence", "first"),
                                   "label": ev.get("label", "")},
                         "direction": a.get("direction", "before"),
                         "within": {"n": wi.get("n"), "unit": wi.get("unit", "months")}}
    return out


def _parse_legacy_within(s, rec, where):
    m = re.match(r"^\s*(\d+)\s*(day|week|month|year)s?\s*$", s or "")
    if m:
        rec(f"{where}: legacy within '{s}' converted to typed form")
        return {"n": int(m.group(1)), "unit": m.group(2) + "s"}
    if s:
        rec(f"{where}: within '{s}' not parseable; dropped")
    return {"n": None, "unit": "months"}


def _build_member(d, rec):
    """Inverse of _clean: a contract dict -> a UI node.

    DRAFT-mode tolerant: unknown/unparseable members are kept VISIBLE as notes
    and every such coercion is reported via rec(). Semantics are never changed
    silently — check_contract() is the fail-closed path.
    """
    if not isinstance(d, dict):
        rec(f"unparseable member kept as a note: {d!r}")
        return new_note("(unparseable)", str(d))
    # a leaf always carries `kind`; a container never does (its `op` is AND/OR,
    # NOT the comparison `op` a measure leaf carries)
    if "kind" not in d and ("op" in d or "members" in d):
        if d.get("op", "AND") not in OPS:
            rec(f"container op {d.get('op')!r} is not AND/OR (kept as authored)")
        return _keep_id(new_container(d.get("op", "AND"), d.get("label", ""),
                                      [_build_member(m, rec) for m in d.get("members", [])]), d)
    k = d.get("kind")
    lbl = d.get("label", "")
    where = f"'{lbl or k}'"
    if k == "demographic":
        sex = d.get("sex", "any")
        if sex in ("both", "", None):                     # legacy free text
            if sex == "both":
                rec(f"{where}: legacy sex 'both' converted to 'any'")
            sex = "any"
        return _keep_id(new_demographic(lbl, d.get("source", _DEMOG_SRC),
                                        d.get("age_min"), d.get("age_max"), sex,
                                        d.get("residence", ""), d.get("simd", "")), d)
    if k == "codes":
        return _keep_id(new_codes(lbl, d.get("source", ""), icd=d.get("icd"),
                                  opcs=d.get("opcs"), read=d.get("read"),
                                  bnf=d.get("bnf"), drug_names=d.get("drug_names"),
                                  when=_load_when(d, rec, where)), d)
    if k == "measure":
        return _keep_id(new_measure(lbl, d.get("source", ""), d.get("measure", ""),
                                    d.get("op", ">="), d.get("value"), d.get("unit", ""),
                                    _load_when(d, rec, where)), d)
    if k == "sample":
        se = d.get("sample_event", {}) or {}
        ev = se.get("event", {}) or {}
        wi = se.get("within") or {}
        if isinstance(wi, str):                           # legacy "6 months"
            wi = _parse_legacy_within(wi, rec, where)
        return _keep_id(new_sample(lbl, ev.get("type", "gp_data"),
                                   ev.get("occurrence", "first"), ev.get("label", ""),
                                   ev.get("codes"), se.get("direction", "before"),
                                   wi.get("n"), wi.get("unit", "months")), d)
    if k == "note":
        return _keep_id(new_note(lbl, d.get("text", "")), d)
    rec(f"unknown kind {k!r} kept as a note ('{lbl}') — it will NOT compile")
    return _keep_id(new_note(lbl or f"(unsupported kind {k!r})", str(d)), d)


def from_contract(data, issues=None):
    """DRAFT load: a requirement YAML/dict -> an editable UI tree.

    Tolerant (for repairing work-in-progress files), but NEVER silent: every
    coercion is appended to `issues` (a caller-supplied list). Approval and
    compilation must instead go through check_contract(), which fails closed.
    """
    rec = issues.append if issues is not None else (lambda m: None)
    data = data or {}
    sv = data.get("schema_version")
    v = _int_version(sv)        # None for bool/str/list/... (never raises)
    sv_out = SCHEMA_VERSION
    if v == SCHEMA_VERSION:
        if type(sv) is not int:            # e.g. 3.0 -> 3
            rec(f"schema_version {sv!r} canonicalized to {SCHEMA_VERSION}")
    elif v in MIGRATABLE_VERSIONS:
        rec(f"schema_version {sv!r} is not the supported version {SCHEMA_VERSION}; "
            f"loaded as a draft and UPGRADED to v{SCHEMA_VERSION} — review "
            "(and re-seal, if it was sealed) before use")
    else:                       # unknown/future/malformed: must NOT be relabelled
        sv_out = sv
        rec(f"schema_version {sv!r} is not supported (this tool is v"
            f"{SCHEMA_VERSION}; it migrates {sorted(MIGRATABLE_VERSIONS)}); "
            "kept as-is — the strict gate will reject it")
    pt = data.get("project_type", "recruitment")
    if pt not in PROJECT_TYPES:               # keep verbatim — validate() will flag it
        rec(f"unknown project_type {pt!r} (kept as authored)")
    req = {"project": data.get("project", ""),
           "project_type": pt,
           "target_n": data.get("target_n", ""),
           "ticket": data.get("ticket", ""),
           "contract": dict(data["contract"]) if isinstance(data.get("contract"), dict) else None,
           "schema_version": sv_out,
           "cohorts": []}
    for gd in data.get("cohorts", []) or []:
        inc = _build_member(gd.get("inclusion") or {"op": "AND", "members": []}, rec)
        if inc.get("node") != "container":               # inclusion must be a container
            rec(f"group '{gd.get('name', '')}': inclusion was a single condition; "
                "wrapped in an AND container")
            inc = new_container("AND", members=[inc])
        g = {"_id": _id(), "name": gd.get("name", ""),
             "inclusion": inc,
             "exclusions": [_build_member(m, rec) for m in (gd.get("exclusions") or [])]}
        _keep_id(g, gd)
        req["cohorts"].append(g)
    if not req["cohorts"]:
        rec("file has no cohorts; started an empty group")
        req["cohorts"] = [new_group("Group 1")]
    return req


# ---------------------------------------------------------------------------
# STRICT GATE (fail-closed) — structural check on a RAW contract dict.
# Approval and compilation require a clean pass; the editor may still open a
# failing file via from_contract() (draft mode), which tolerates and reports.
# ---------------------------------------------------------------------------
_TOP_KEYS = {"contract", "project", "project_type", "target_n", "ticket",
             "schema_version", "cohorts"}
_HEADER_KEYS = {"id", "version", "status", "requested_by", "approved_by",
                "approved_on", "body_sha256", "references"}
_GROUP_KEYS = {"id", "name", "inclusion", "exclusions"}
_CONTAINER_KEYS = {"id", "op", "label", "members"}
_LEAF_KEYS = {
    "demographic": {"id", "kind", "label", "source", "age_min", "age_max",
                    "sex", "residence", "simd"},
    "codes": {"id", "kind", "label", "source", "icd", "opcs", "read", "bnf",
              "drug_names", "when"},
    "measure": {"id", "kind", "label", "source", "measure", "op", "value",
                "unit", "when"},
    "sample": {"id", "kind", "label", "sample_event"},
    "note": {"id", "kind", "label", "text"},
}
_CODE_FIELDS = ("icd", "opcs", "read", "bnf", "drug_names")


def _is_code_list(v):
    return (isinstance(v, list) and v
            and all(isinstance(x, str) and x.strip() for x in v))


_WHEN_KEYS = {"window", "anchor"}
_WINDOW_KEYS = {"from", "to"}
_ANCHOR_KEYS = {"event", "direction", "within"}
_ANCHOR_EVENT_KEYS = {"source", "vocab", "codes", "occurrence", "label"}
_WITHIN_KEYS = {"n", "unit"}


def _check_within(w, where, errs):
    if not isinstance(w, dict):
        errs.append(f"{where}: within must be a mapping {{n, unit}}")
        return
    extra = set(w) - _WITHIN_KEYS
    if extra:
        errs.append(f"{where}: within has unknown field(s): " + ", ".join(sorted(extra)))
    if not isinstance(w.get("n"), int) or w.get("n", 0) < 1:
        errs.append(f"{where}: within.n must be a positive integer")
    if w.get("unit") not in WITHIN_UNITS:
        errs.append(f"{where}: within.unit must be one of: " + ", ".join(WITHIN_UNITS))


def _check_when(w, where, errs):
    if not isinstance(w, dict):
        errs.append(f"{where}: when must be a mapping")
        return
    extra = set(w) - _WHEN_KEYS
    if extra:
        errs.append(f"{where}: when has unknown field(s): " + ", ".join(sorted(extra)))
    win = w.get("window")
    if win is not None:
        if not isinstance(win, dict) or not win or set(win) - _WINDOW_KEYS:
            errs.append(f"{where}: when.window must be {{from and/or to}}")
        else:
            for k, v in win.items():
                if not isinstance(v, str) or not _DATE_RE.match(v):
                    errs.append(f"{where}: when.window.{k} must be an ISO date YYYY-MM-DD")
    a = w.get("anchor")
    if a is not None:
        if not isinstance(a, dict):
            errs.append(f"{where}: when.anchor must be a mapping")
            return
        extra = set(a) - _ANCHOR_KEYS
        if extra:
            errs.append(f"{where}: anchor has unknown field(s): " + ", ".join(sorted(extra)))
        ev = a.get("event")
        if not isinstance(ev, dict):
            errs.append(f"{where}: anchor.event is required")
        else:
            extra = set(ev) - _ANCHOR_EVENT_KEYS
            if extra:
                errs.append(f"{where}: anchor.event has unknown field(s): "
                            + ", ".join(sorted(extra)))
            if not ev.get("source"):
                errs.append(f"{where}: anchor.event.source is required")
            if not ev.get("vocab"):
                errs.append(f"{where}: anchor.event.vocab is required")
            if not _is_code_list(ev.get("codes")):
                errs.append(f"{where}: anchor.event.codes must be a non-empty "
                            "list of code strings")
            if ev.get("occurrence", "first") not in OCCURRENCE:
                errs.append(f"{where}: anchor.event.occurrence must be first or last")
        if a.get("direction") not in DIRECTION:
            errs.append(f"{where}: anchor.direction must be before or after")
        if a.get("within") is not None:
            _check_within(a["within"], where, errs)
    if not win and a is None:
        errs.append(f"{where}: when must contain a window and/or an anchor")


def _check_header(hdr, errs):
    if not isinstance(hdr, dict):
        errs.append("contract header must be a mapping")
        return
    extra = set(hdr) - _HEADER_KEYS
    if extra:
        errs.append("contract header: unknown field(s): " + ", ".join(sorted(extra)))
    if hdr.get("status") not in CONTRACT_STATUSES:
        errs.append("contract.status must be one of: " + ", ".join(CONTRACT_STATUSES))
    if hdr.get("status") == "agreed":
        for f in ("id", "body_sha256"):
            if not hdr.get(f):
                errs.append(f"an agreed contract must carry contract.{f}")
    refs = hdr.get("references")
    if refs is not None and (not isinstance(refs, dict) or set(refs) - {"extraction_spec"}):
        errs.append("contract.references may only contain: extraction_spec")


def check_contract(data):
    """Return a list of gate failures for a raw contract dict ([] = passes).

    Rejects (never coerces): unsupported schema_version, unknown fields,
    unknown kinds/ops/project types, missing or duplicate persistent ids,
    malformed timing/threshold structures, and — for a sealed (`agreed`)
    header — a body hash that no longer matches the body.
    """
    errs = []
    if not isinstance(data, dict):
        return ["contract must be a YAML mapping"]

    def unknown(d, allowed, where):
        extra = set(d) - allowed
        if extra:
            errs.append(f"{where}: unknown field(s): " + ", ".join(sorted(extra)))

    unknown(data, _TOP_KEYS, "top level")
    sv = data.get("schema_version")
    # integral numbers accepted (3.0 == 3, matching JSON Schema's const: 3);
    # bools/strings/containers are rejected by _int_version
    if _int_version(sv) != SCHEMA_VERSION:
        errs.append(f"unsupported schema_version {sv!r} "
                    f"(supported: {SCHEMA_VERSION})")
    if data.get("project_type") not in PROJECT_TYPES:
        errs.append(f"project_type {data.get('project_type')!r} must be one of: "
                    + ", ".join(PROJECT_TYPES))
    if data.get("contract") is not None:
        _check_header(data["contract"], errs)
        if (isinstance(data["contract"], dict)
                and data["contract"].get("status") == "agreed"
                and data["contract"].get("body_sha256")
                and hash_status(data) == "changed"):
            errs.append("contract is 'agreed' but the body has CHANGED since it was "
                        "sealed (body_sha256 does not match)")
    seen = set()

    def check_id(d, where):
        i = d.get("id")
        if not i:
            errs.append(f"{where}: missing persistent id")
        elif i in seen:
            errs.append(f"{where}: duplicate id {i!r}")
        else:
            seen.add(i)

    def member(d, where):
        if not isinstance(d, dict):
            errs.append(f"{where}: member must be a mapping")
            return
        # container iff no `kind` (a measure leaf also has an `op` — the
        # comparison operator — so `op` alone must not mean container)
        if "kind" not in d and ("op" in d or "members" in d):
            check_id(d, where)
            unknown(d, _CONTAINER_KEYS, where)
            if d.get("op") not in OPS:
                errs.append(f"{where}: container op {d.get('op')!r} must be AND or OR")
            ms = d.get("members")
            if not isinstance(ms, list):
                errs.append(f"{where}: container members must be a list")
                return
            for j, m in enumerate(ms, 1):
                member(m, f"{where} > member {j}")
            return
        k = d.get("kind")
        if k not in KINDS:
            errs.append(f"{where}: unknown kind {k!r} (must be one of: " + ", ".join(KINDS) + ")")
            return
        check_id(d, where)
        unknown(d, _LEAF_KEYS[k], where)
        if k == "codes":
            # present-by-KEY: an explicit null is a typed-list error (matching
            # the JSON Schema), not silently treated as absent
            present = [f for f in _CODE_FIELDS if f in d]
            for f in present:
                if not _is_code_list(d[f]):
                    errs.append(f"{where}: {f} must be a non-empty list of "
                                "code strings")
            if not present:      # would compile to an empty WHERE ()
                errs.append(f"{where}: a codes criterion needs at least one of: "
                            + ", ".join(_CODE_FIELDS))
        if k == "demographic":
            if d.get("sex") is not None and d["sex"] not in SEXES:
                errs.append(f"{where}: sex {d['sex']!r} must be one of: " + ", ".join(SEXES))
            for f in ("age_min", "age_max"):
                if d.get(f) is not None and not isinstance(d[f], int):
                    errs.append(f"{where}: {f} must be an integer")
        elif k == "measure":
            if d.get("op") not in CMP_OPS:
                errs.append(f"{where}: measure op {d.get('op')!r} must be one of: "
                            + ", ".join(CMP_OPS))
            if not isinstance(d.get("value"), (int, float)) or isinstance(d.get("value"), bool):
                errs.append(f"{where}: measure value must be a number")
            if not d.get("measure"):
                errs.append(f"{where}: measure name is required")
        elif k == "sample":
            se = d.get("sample_event")
            if not isinstance(se, dict):
                errs.append(f"{where}: sample_event is required")
            else:
                ev = se.get("event") or {}
                if ev.get("type") not in EVENT_TYPES:
                    errs.append(f"{where}: event type {ev.get('type')!r} must be one of: "
                                + ", ".join(EVENT_TYPES))
                codes = ev.get("codes")
                if ev.get("type") == "lab_result":   # free text: may be []/absent
                    if codes is not None and (not isinstance(codes, list) or not all(
                            isinstance(x, str) and x.strip() for x in codes)):
                        errs.append(f"{where}: event codes must be a list of "
                                    "code strings")
                elif not _is_code_list(codes):       # coded events NEED codes
                    errs.append(f"{where}: event codes must be a non-empty list "
                                "of code strings")
                if ev.get("occurrence", "first") not in OCCURRENCE:
                    errs.append(f"{where}: occurrence must be first or last")
                if se.get("direction") not in DIRECTION:
                    errs.append(f"{where}: direction must be before or after")
                if se.get("within") is not None:
                    _check_within(se["within"], where, errs)
        if k in ("codes", "measure") and d.get("when") is not None:
            _check_when(d["when"], where, errs)

    cohorts = data.get("cohorts")
    if not isinstance(cohorts, list) or not cohorts:
        errs.append("cohorts must be a non-empty list")
        return errs
    for gi, g in enumerate(cohorts, 1):
        gname = (g.get("name") if isinstance(g, dict) else None) or f"group {gi}"
        if not isinstance(g, dict):
            errs.append(f"{gname}: group must be a mapping")
            continue
        check_id(g, gname)
        unknown(g, _GROUP_KEYS, gname)
        inc = g.get("inclusion")
        if (not isinstance(inc, dict) or "kind" in inc
                or not ("op" in inc or "members" in inc)):
            errs.append(f"{gname}: inclusion must be a container (op + members)")
        else:
            member(inc, f"{gname} inclusion")
        ex = g.get("exclusions", [])
        if not isinstance(ex, list):
            errs.append(f"{gname}: exclusions must be a list")
        else:
            for j, m in enumerate(ex, 1):
                member(m, f"{gname} exclusion {j}")
    return errs


# ---------------------------------------------------------------------------
# Validation (basic shape on the UI tree — level 1; registry conformance is
# level 2 = registry.check_sources; per-site feasibility is level 3).
# ---------------------------------------------------------------------------
def _validate_node(n, gname, errs, path):
    """`path` is the positional address shown in the UI cards, e.g.
    'inclusion 2.1' = first child of the second top-level inclusion item."""
    where = f"{gname} › {path}"
    if n.get("node") == "container":
        if n.get("op") not in OPS:
            errs.append(f"{where}: container op must be AND or OR.")
        if not n.get("members"):
            errs.append(f"{where}: this {OP_NAME.get(n.get('op'), '?')} container is "
                        "empty — add at least one condition, or remove it.")
        for i, m in enumerate(n.get("members", []), 1):
            _validate_node(m, gname, errs, f"{path}.{i}")
        return
    k = n.get("kind")
    lbl = n.get("label") or k
    if k == "codes":
        if not any(n.get(f) for f in ("icd", "opcs", "read", "bnf", "drug_names")):
            errs.append(f"{where}: codes condition '{lbl}' has no codes.")
        _validate_when(n, where, lbl, errs)
    elif k == "measure":
        if n.get("value") is None:
            errs.append(f"{where}: measure '{lbl}' has no threshold value.")
        if n.get("op") not in CMP_OPS:
            errs.append(f"{where}: measure '{lbl}' has an invalid comparison.")
        _validate_when(n, where, lbl, errs)
    elif k == "demographic":
        a, b = n.get("age_min"), n.get("age_max")
        if a is not None and b is not None and a > b:
            errs.append(f"{where}: '{lbl}' has age_min > age_max.")
        if n.get("sex") not in SEXES:
            errs.append(f"{where}: '{lbl}' sex must be one of: " + ", ".join(SEXES) + ".")
    elif k == "sample":
        ev = n.get("sample_event", {}).get("event", {})
        if ev.get("type") not in EVENT_TYPES:
            errs.append(f"{where}: '{lbl}' has an invalid event type.")
        if ev.get("type") != "lab_result" and not ev.get("codes"):
            errs.append(f"{where}: '{lbl}' event needs at least one code.")
        if n.get("sample_event", {}).get("direction") not in DIRECTION:
            errs.append(f"{where}: '{lbl}' direction must be before or after.")
    elif k == "note":
        if not n.get("text", "").strip():
            errs.append(f"{where}: note '{lbl}' has no text.")


def _validate_when(n, where, lbl, errs):
    w = n.get("when")
    if not isinstance(w, dict):
        return
    for k, v in (w.get("window") or {}).items():
        if v and not _DATE_RE.match(str(v)):
            errs.append(f"{where}: '{lbl}' window {k} must be an ISO date (YYYY-MM-DD).")
    a = w.get("anchor")
    if isinstance(a, dict) and a.get("event"):
        if not a["event"].get("codes"):
            errs.append(f"{where}: '{lbl}' anchor event needs at least one code.")


def validate(req):
    errs = []
    if not req.get("project", "").strip():
        errs.append("Project title is required.")
    if req.get("project_type") not in PROJECT_TYPES:
        errs.append("Project type must be one of: " + ", ".join(PROJECT_TYPES) + ".")
    if not req.get("cohorts"):
        errs.append("Add at least one group.")
    names = [g.get("name", "").strip() for g in req.get("cohorts", [])]
    for dup in sorted({n for n in names if n and names.count(n) > 1}):
        errs.append(f"Group name '{dup}' is used more than once — names must be "
                    "unique (each names one downstream build).")
    for i, g in enumerate(req.get("cohorts", []), 1):
        gname = g.get("name") or f"Group {i}"
        if not g.get("name", "").strip():
            errs.append(f"Group {i}: a name is required.")
        inc = g.get("inclusion")
        if not inc or not inc.get("members"):
            errs.append(f"{gname}: inclusion must have at least one condition.")
        else:
            if inc.get("op") not in OPS:
                errs.append(f"{gname} › inclusion: container op must be AND or OR.")
            for j, m in enumerate(inc.get("members", []), 1):
                _validate_node(m, gname, errs, f"inclusion {j}")
        for j, m in enumerate(g.get("exclusions", []), 1):
            _validate_node(m, gname, errs, f"exclusion {j}")
    return errs


def notes_in(contract_dict):
    """(id, label, position) of `note` leaves in a raw contract dict — the
    position uses the same addressing as validate() and the UI ordinal chips,
    e.g. 'Group A › exclusion 2'. Notes block compilation."""
    found = []

    def member(d, path):
        if not isinstance(d, dict):
            return
        if "kind" not in d and ("op" in d or "members" in d):
            for i, m in enumerate(d.get("members") or [], 1):
                member(m, f"{path}.{i}")
        elif d.get("kind") == "note":
            found.append((d.get("id", "?"), d.get("label", ""), path))
    for g in (contract_dict or {}).get("cohorts") or []:
        gname = g.get("name") or "?"
        inc = g.get("inclusion") or {}
        for i, m in enumerate(inc.get("members") or [], 1):
            member(m, f"{gname} › inclusion {i}")
        for j, m in enumerate(g.get("exclusions") or [], 1):
            member(m, f"{gname} › exclusion {j}")
    return found


# ---------------------------------------------------------------------------
# JSON Schema — the same contract, as a JSON Schema document (draft-07), for
# non-Python consumers. `requirement.schema.json` is generated from this and
# kept in sync by a test.
# ---------------------------------------------------------------------------
def json_schema():
    # items must contain a non-whitespace character (mirrors _is_code_list)
    code_str = {"type": "string", "pattern": "\\S"}
    codes_list = {"type": "array", "items": code_str, "minItems": 1}
    within = {"type": "object", "additionalProperties": False, "required": ["n", "unit"],
              "properties": {"n": {"type": "integer", "minimum": 1},
                             "unit": {"enum": WITHIN_UNITS}}}
    when = {"type": "object", "additionalProperties": False,
            "properties": {
                "window": {"type": "object", "additionalProperties": False, "minProperties": 1,
                           "properties": {"from": {"type": "string", "pattern": _DATE_RE.pattern},
                                          "to": {"type": "string", "pattern": _DATE_RE.pattern}}},
                "anchor": {"type": "object", "additionalProperties": False,
                           "required": ["event", "direction"],
                           "properties": {
                               "event": {"type": "object", "additionalProperties": False,
                                         "required": ["source", "vocab", "codes"],
                                         "properties": {"source": {"type": "string"},
                                                        "vocab": {"type": "string"},
                                                        "codes": codes_list,
                                                        "occurrence": {"enum": OCCURRENCE},
                                                        "label": {"type": "string"}}},
                               "direction": {"enum": DIRECTION},
                               "within": within}}}}
    base = {"id": {"type": "string"}, "kind": {"enum": KINDS}, "label": {"type": "string"}}
    leaves = {
        "demographic": {"source": {"type": "string"},
                        "age_min": {"type": "integer"}, "age_max": {"type": "integer"},
                        "sex": {"enum": SEXES}, "residence": {"type": "string"},
                        "simd": {"type": "string"}},
        "codes": {"source": {"type": "string"}, "icd": codes_list, "opcs": codes_list,
                  "read": codes_list, "bnf": codes_list, "drug_names": codes_list,
                  "when": when},
        "measure": {"source": {"type": "string"}, "measure": {"type": "string"},
                    "op": {"enum": CMP_OPS}, "value": {"type": "number"},
                    "unit": {"type": "string"}, "when": when},
        "sample": {"sample_event": {
            "type": "object", "additionalProperties": False,
            "required": ["event", "direction"],
            "properties": {"event": {
                "type": "object", "additionalProperties": False,
                "required": ["type"],
                "properties": {"type": {"enum": EVENT_TYPES},
                               "occurrence": {"enum": OCCURRENCE},
                               "label": {"type": "string"},
                               "codes": {"type": "array", "items": code_str}},
                # coded event types NEED codes; lab_result is free text
                "if": {"properties": {"type": {"const": "lab_result"}}},
                "else": {"required": ["codes"],
                         "properties": {"codes": {"type": "array",
                                                  "items": code_str,
                                                  "minItems": 1}}}},
                           "direction": {"enum": DIRECTION},
                           "within": within}}},
        "note": {"text": {"type": "string"}},
    }
    leaf_schemas = []
    for k, props in leaves.items():
        ls = {"type": "object", "additionalProperties": False,
              "required": ["id", "kind"],
              "properties": {**base, **props, "kind": {"const": k}}}
        if k == "codes":        # at least one vocabulary field (mirrors the gate)
            ls["anyOf"] = [{"required": [f]} for f in _CODE_FIELDS]
        leaf_schemas.append(ls)
    member = {"anyOf": [{"$ref": "#/definitions/container"}] + leaf_schemas}
    container = {"type": "object", "additionalProperties": False,
                 "required": ["id", "op", "members"],
                 "properties": {"id": {"type": "string"}, "op": {"enum": OPS},
                                "label": {"type": "string"},
                                "members": {"type": "array",
                                            "items": {"$ref": "#/definitions/member"}}}}
    header = {"type": "object", "additionalProperties": False,
              "properties": {"id": {"type": "string"}, "version": {"type": "integer"},
                             "status": {"enum": CONTRACT_STATUSES},
                             "requested_by": {"type": "string"},
                             "approved_by": {"type": "string"},
                             "approved_on": {"type": "string"},
                             "body_sha256": {"type": "string"},
                             "references": {"type": "object", "additionalProperties": False,
                                            "properties": {"extraction_spec":
                                                           {"type": "string"}}}}}
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Cohort requirement contract",
        "description": "Generated from requirement_schema.py — do not edit by hand.",
        "type": "object", "additionalProperties": False,
        "required": ["project", "project_type", "schema_version", "cohorts"],
        "properties": {
            "contract": header,
            "project": {"type": "string"},
            "project_type": {"enum": PROJECT_TYPES},
            "target_n": {"type": "string"},
            "ticket": {"type": "string"},
            "schema_version": {"const": SCHEMA_VERSION},
            "cohorts": {"type": "array", "minItems": 1, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "name", "inclusion"],
                "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                               "inclusion": {"$ref": "#/definitions/container"},
                               "exclusions": {"type": "array",
                                              "items": {"$ref": "#/definitions/member"}}}}}},
        "definitions": {"container": container, "member": member},
    }


# ---------------------------------------------------------------------------
# Worked example — deliberately GENERIC / illustrative (placeholder codes and
# labels). It only shows the STRUCTURE: two self-contained groups, AND/OR
# nesting, code conditions across sources, and ordered exclusions.
# ---------------------------------------------------------------------------
def _condition_union():
    return new_container("OR", "Condition of interest (any source)", [
        new_codes("Condition in hospital data", "hospital_admissions", icd=["A00"]),
        new_codes("Condition in primary care", "gp_events", read=["X1111"]),
    ])


def _adults():
    return new_demographic("Adults", _DEMOG_SRC, age_min=18, age_max=80, sex="any")


def build_example():
    req = new_requirement()
    req.update(project="Example cohort request (edit me)",
               project_type="recruitment", target_n="approx. N per group", ticket="")

    a = new_group("Group A — cases")
    a_members = [
        _adults(),
        _condition_union(),
        new_container("OR", "A second condition (placeholder)", [
            new_codes("Second condition (primary care)", "gp_events", read=["X2222"]),
            new_codes("Second condition (hospital)", "hospital_admissions", icd=["A01"]),
        ]),
    ]
    if ENABLE_SAMPLES:        # sample kind offered: show an event-anchored condition
        a_members.append(new_sample("Has a sample before first diagnosis",
                                    event_type="gp_data", occurrence="first",
                                    event_label="First recorded diagnosis", codes=["X1111"],
                                    direction="before", within_n=6, within_unit="months"))
    a["inclusion"] = new_container("AND", members=a_members)
    a["exclusions"] = [
        new_codes("Comorbidity to exclude", "hospital_admissions", icd=["B00"]),
        new_note("Other criterion (no code yet)",
                 "Describe any criterion that has no agreed code."),
    ]

    b = new_group("Group B — controls")
    b["inclusion"] = new_container("AND", members=[_adults(), _condition_union()])
    b["exclusions"] = [
        new_codes("Exclude a condition variant", "gp_events", read=["X3333"]),
        new_codes("Comorbidity to exclude", "hospital_admissions", icd=["B00"]),
    ]

    req["cohorts"] = [a, b]
    return req
