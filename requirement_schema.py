"""Single source of truth for the cohort requirement schema.

Imported by BOTH the Streamlit app and (eventually) the pipeline, so the two can
never drift. Holds:
  * the controlled vocabularies (project types, ops, kinds, event types …),
  * node factories (new_* — each carries an internal `_id` for the UI tree),
  * to_contract(req)  -> a clean dict ready to YAML-dump (persistent `id` per
                         group/container/leaf; internal `_id`/flags stripped),
  * from_contract()   -> DRAFT load: tolerant, but reports every coercion,
  * check_contract()  -> STRICT GATE: fail-closed check on a raw contract dict
                         (approval / compilation require a clean pass),
  * validate(req)     -> a list of human-readable problems (basic shape checks),
  * build_example()   -> the worked two-group example (mirrors examples/*.yaml).

Design (see docs/SPEC.md and plan.md): each GROUP is self-contained = one RDMP
build. inclusion is a CONTAINER (AND=INTERSECT / OR=UNION) built first;
exclusions are an ORDERED list subtracted in turn (root EXCEPT). Leaves are
cohort sets of kind demographic / codes / sample / note.

ONE SCHEMA FOR ALL ENVIRONMENTS: the schema always accepts every kind and
project type — a given schema_version means exactly one thing everywhere.
The env flag COHORT_ENABLE_SAMPLES=1 only widens what the UI OFFERS
(UI_KINDS / UI_PROJECT_TYPES: adds the `sample` kind and `biobank` type to the
authoring menus); it never changes what parses or validates.
"""
import os
import uuid

ENABLE_SAMPLES = os.environ.get("COHORT_ENABLE_SAMPLES", "").lower() in ("1", "true", "yes", "on")

OPS = ["AND", "OR"]
# Normative vocabularies (what the schema ACCEPTS — identical everywhere).
KINDS = ["demographic", "codes", "sample", "note"]
PROJECT_TYPES = ["recruitment", "registry", "biobank", "other"]
# What the authoring UI OFFERS (feature-flag gated; a superset never parses
# differently, the flag only surfaces extra choices in the form).
UI_KINDS = (["demographic", "codes", "sample", "note"] if ENABLE_SAMPLES
            else ["demographic", "codes", "note"])
UI_PROJECT_TYPES = (["recruitment", "biobank"] if ENABLE_SAMPLES
                    else ["recruitment", "registry", "other"])

# Sample / event-anchored selection — SHARE variant only (surfaced when ENABLE_SAMPLES).
EVENT_TYPES = ["hospitalisation", "medicine", "gp_data", "lab_result"]
EVENT_VOCAB = {"hospitalisation": "ICD-10", "medicine": "BNF",
               "gp_data": "READ", "lab_result": "free text"}
OCCURRENCE = ["first", "last"]
DIRECTION = ["before", "after"]
WITHIN_UNITS = ["days", "weeks", "months", "years"]
SCHEMA_VERSION = 1
_DEMOG_SRC = "SHARE_Demography" if ENABLE_SAMPLES else "Demographics"


def _id():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Node factories (UI-side nodes carry `_id`; stripped on export).
# ---------------------------------------------------------------------------
def new_container(op="AND", label="", members=None):
    return {"_id": _id(), "node": "container", "op": op, "label": label,
            "members": members if members is not None else []}


def new_demographic(label="", source=_DEMOG_SRC, age_min=None, age_max=None,
                    sex="both", residence="", simd=""):
    return {"_id": _id(), "node": "leaf", "kind": "demographic", "label": label,
            "source": source, "age_min": age_min, "age_max": age_max,
            "sex": sex, "residence": residence, "simd": simd}


def new_codes(label="", source="", icd=None, read=None, bnf=None, drug_names=None):
    return {"_id": _id(), "node": "leaf", "kind": "codes", "label": label, "source": source,
            "icd": icd or [], "read": read or [], "bnf": bnf or [], "drug_names": drug_names or []}


def new_sample(label="", event_type="gp_data", occurrence="first", event_label="",
               codes=None, direction="before", within=""):
    # SHARE variant: "person has >=1 sample positioned in time vs an index event"
    return {"_id": _id(), "node": "leaf", "kind": "sample", "label": label,
            "sample_event": {
                "event": {"type": event_type, "occurrence": occurrence,
                          "label": event_label, "codes": codes or []},
                "direction": direction, "within": within}}


def new_note(label="", text=""):
    return {"_id": _id(), "node": "leaf", "kind": "note", "label": label, "text": text}


def new_leaf(kind, label=""):
    return {"demographic": new_demographic, "codes": new_codes,
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
            "schema_version": SCHEMA_VERSION, "cohorts": [new_group("Group 1")]}


# ---------------------------------------------------------------------------
# Export: UI tree -> clean contract dict. The internal `_id` is exported as a
# PERSISTENT `id` (so criteria stay addressable across versions — for review
# comments, diffs, feasibility errors); other internal flags/empties are
# stripped.
# ---------------------------------------------------------------------------
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
        for f in ("sex", "residence", "simd"):
            if n.get(f):
                out[f] = n[f]
    elif k == "codes":
        if n.get("source"):
            out["source"] = n["source"]
        for f in ("icd", "read", "bnf", "drug_names"):
            if n.get(f):
                out[f] = list(n[f])
    elif k == "sample":
        ev = n["sample_event"]["event"]
        event = {"type": ev["type"], "occurrence": ev["occurrence"]}
        if ev.get("label"):
            event["label"] = ev["label"]
        event["codes"] = list(ev.get("codes", []))
        se = {"event": event, "direction": n["sample_event"]["direction"]}
        if n["sample_event"].get("within"):
            se["within"] = n["sample_event"]["within"]
        out["sample_event"] = se
    elif k == "note":
        out["text"] = n.get("text", "")
    return out


def _keep_id(node, d):
    """Preserve a contract `id` on the rebuilt UI node (persistent identity)."""
    if isinstance(d, dict) and d.get("id"):
        node["_id"] = str(d["id"])
    return node


def _build_member(d, rec):
    """Inverse of _clean: a contract dict -> a UI node.

    DRAFT-mode tolerant: unknown/unparseable members are kept VISIBLE as notes
    and every such coercion is reported via rec(). Semantics are never changed
    silently — check_contract() is the fail-closed path.
    """
    if not isinstance(d, dict):
        rec(f"unparseable member kept as a note: {d!r}")
        return new_note("(unparseable)", str(d))
    if "op" in d or "members" in d:                       # container
        if d.get("op", "AND") not in OPS:
            rec(f"container op {d.get('op')!r} is not AND/OR (kept as authored)")
        return _keep_id(new_container(d.get("op", "AND"), d.get("label", ""),
                                      [_build_member(m, rec) for m in d.get("members", [])]), d)
    k = d.get("kind")
    if k == "demographic":
        return _keep_id(new_demographic(d.get("label", ""), d.get("source", "Demographics"),
                                        d.get("age_min"), d.get("age_max"), d.get("sex", "both"),
                                        d.get("residence", ""), d.get("simd", "")), d)
    if k == "codes":
        return _keep_id(new_codes(d.get("label", ""), d.get("source", ""), d.get("icd"),
                                  d.get("read"), d.get("bnf"), d.get("drug_names")), d)
    if k == "sample":
        se = d.get("sample_event", {}) or {}
        ev = se.get("event", {}) or {}
        return _keep_id(new_sample(d.get("label", ""), ev.get("type", "gp_data"),
                                   ev.get("occurrence", "first"), ev.get("label", ""),
                                   ev.get("codes"), se.get("direction", "before"),
                                   se.get("within", "")), d)
    if k == "note":
        return _keep_id(new_note(d.get("label", ""), d.get("text", "")), d)
    rec(f"unknown kind {k!r} kept as a note ('{d.get('label', '')}') — it will NOT compile")
    return _keep_id(new_note(d.get("label") or f"(unsupported kind {k!r})", str(d)), d)


def from_contract(data, issues=None):
    """DRAFT load: a requirement YAML/dict -> an editable UI tree.

    Tolerant (for repairing work-in-progress files), but NEVER silent: every
    coercion is appended to `issues` (a caller-supplied list). Approval and
    compilation must instead go through check_contract(), which fails closed.
    """
    rec = issues.append if issues is not None else (lambda m: None)
    data = data or {}
    sv = data.get("schema_version")
    if sv != SCHEMA_VERSION:
        rec(f"schema_version {sv!r} is not the supported version {SCHEMA_VERSION} "
            "(loaded as a draft; the strict gate will reject it)")
    pt = data.get("project_type", "recruitment")
    if pt not in PROJECT_TYPES:               # keep verbatim — validate() will flag it
        rec(f"unknown project_type {pt!r} (kept as authored)")
    req = {"project": data.get("project", ""),
           "project_type": pt,
           "target_n": data.get("target_n", ""),
           "ticket": data.get("ticket", ""),
           "schema_version": data.get("schema_version", SCHEMA_VERSION),
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
_TOP_KEYS = {"project", "project_type", "target_n", "ticket", "schema_version", "cohorts"}
_GROUP_KEYS = {"id", "name", "inclusion", "exclusions"}
_CONTAINER_KEYS = {"id", "op", "label", "members"}
_LEAF_KEYS = {
    "demographic": {"id", "kind", "label", "source", "age_min", "age_max",
                    "sex", "residence", "simd"},
    "codes": {"id", "kind", "label", "source", "icd", "read", "bnf", "drug_names"},
    "sample": {"id", "kind", "label", "sample_event"},
    "note": {"id", "kind", "label", "text"},
}


def check_contract(data):
    """Return a list of gate failures for a raw contract dict ([] = passes).

    Rejects (never coerces): unsupported schema_version, unknown fields,
    unknown kinds/ops/project types, missing or duplicate persistent ids.
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
    if sv != SCHEMA_VERSION:
        errs.append(f"unsupported schema_version {sv!r} (supported: {SCHEMA_VERSION})")
    if data.get("project_type") not in PROJECT_TYPES:
        errs.append(f"project_type {data.get('project_type')!r} must be one of: "
                    + ", ".join(PROJECT_TYPES))
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
        if "op" in d or "members" in d:                   # container
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
        if not isinstance(inc, dict) or not ("op" in inc or "members" in inc):
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


def to_contract(req):
    out = {"project": req.get("project", ""),
           "project_type": req.get("project_type", ""),
           "target_n": req.get("target_n", ""),
           "schema_version": req.get("schema_version", SCHEMA_VERSION)}
    if req.get("ticket"):
        out["ticket"] = req["ticket"]
    out["cohorts"] = [{"id": g["_id"], "name": g.get("name", ""),
                       "inclusion": _clean(g["inclusion"]),
                       "exclusions": [_clean(m) for m in g.get("exclusions", [])]}
                      for g in req.get("cohorts", [])]
    return out


# ---------------------------------------------------------------------------
# Validation (basic shape only — semantics live downstream in the pipeline).
# ---------------------------------------------------------------------------
def _validate_node(n, gname, project_type, errs):
    if n.get("node") == "container":
        if n.get("op") not in OPS:
            errs.append(f"{gname}: container op must be AND or OR.")
        if not n.get("members"):
            errs.append(f"{gname}: a {n.get('op', '?')} container has no members.")
        for m in n.get("members", []):
            _validate_node(m, gname, project_type, errs)
        return
    k = n.get("kind")
    lbl = n.get("label") or k
    if k == "codes":
        if not any(n.get(f) for f in ("icd", "read", "bnf", "drug_names")):
            errs.append(f"{gname}: codes condition '{lbl}' has no codes.")
    elif k == "demographic":
        a, b = n.get("age_min"), n.get("age_max")
        if a is not None and b is not None and a > b:
            errs.append(f"{gname}: '{lbl}' has age_min > age_max.")
    elif k == "sample":
        ev = n.get("sample_event", {}).get("event", {})
        if ev.get("type") not in EVENT_TYPES:
            errs.append(f"{gname}: '{lbl}' has an invalid event type.")
        if ev.get("type") != "lab_result" and not ev.get("codes"):
            errs.append(f"{gname}: '{lbl}' event needs at least one code.")
        if n.get("sample_event", {}).get("direction") not in DIRECTION:
            errs.append(f"{gname}: '{lbl}' direction must be before or after.")
    elif k == "note":
        if not n.get("text", "").strip():
            errs.append(f"{gname}: note '{lbl}' has no text.")


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
    ptype = req.get("project_type")
    for i, g in enumerate(req.get("cohorts", []), 1):
        gname = g.get("name") or f"Group {i}"
        if not g.get("name", "").strip():
            errs.append(f"Group {i}: a name is required.")
        inc = g.get("inclusion")
        if not inc or not inc.get("members"):
            errs.append(f"{gname}: inclusion must have at least one condition.")
        elif inc:
            _validate_node(inc, gname, ptype, errs)
        for m in g.get("exclusions", []):
            _validate_node(m, gname, ptype, errs)
    return errs


# ---------------------------------------------------------------------------
# Worked example — deliberately GENERIC / illustrative (placeholder codes and
# labels). It only shows the STRUCTURE: two self-contained groups, AND/OR
# nesting, code conditions across sources, and ordered exclusions.
# ---------------------------------------------------------------------------
def _src(hospital, gp):
    """Source names differ slightly between the SHARE variant and general mode."""
    return (hospital, gp) if not ENABLE_SAMPLES else ("SMR01", "GP")


def _condition_union():
    h, gp = _src("hospital", "primary_care")
    return new_container("OR", "Condition of interest (any source)", [
        new_codes("Condition in hospital data", h, icd=["A00"]),
        new_codes("Condition in primary care", gp, read=["X1111"]),
    ])


def _adults():
    return new_demographic("Adults", _DEMOG_SRC,
                           age_min=18, age_max=80, sex="both", residence="", simd="")


def build_example():
    req = new_requirement()
    req.update(project="Example cohort request (edit me)",
               project_type=PROJECT_TYPES[0], target_n="approx. N per group", ticket="")
    h, gp = _src("hospital", "primary_care")

    a = new_group("Group A — cases")
    a_members = [
        _adults(),
        _condition_union(),
        new_container("OR", "A second condition (placeholder)", [
            new_codes("Second condition (primary care)", gp, read=["X2222"]),
            new_codes("Second condition (hospital)", h, icd=["A01"]),
        ]),
    ]
    if ENABLE_SAMPLES:        # SHARE variant: add an event-anchored sample condition
        a_members.append(new_sample("Has a sample before first diagnosis",
                                    event_type="gp_data", occurrence="first",
                                    event_label="First recorded diagnosis", codes=["X1111"],
                                    direction="before", within="6 months"))
    a["inclusion"] = new_container("AND", members=a_members)
    a["exclusions"] = [
        new_codes("Comorbidity to exclude", h, icd=["B00"]),
        new_note("Other criterion (no code yet)",
                 "Describe any criterion that has no agreed code."),
    ]

    b = new_group("Group B — controls")
    b["inclusion"] = new_container("AND", members=[_adults(), _condition_union()])
    b["exclusions"] = [
        new_codes("Exclude a condition variant", gp, read=["X3333"]),
        new_codes("Comorbidity to exclude", h, icd=["B00"]),
    ]

    req["cohorts"] = [a, b]
    return req
