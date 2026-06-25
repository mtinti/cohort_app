"""Single source of truth for the cohort requirement schema.

Imported by BOTH the Streamlit app and (eventually) the pipeline, so the two can
never drift. Holds:
  * the controlled vocabularies (project types, ops, kinds, event types …),
  * node factories (new_* — each carries an internal `_id` for the UI tree),
  * to_contract(req) -> a clean dict ready to YAML-dump (strips _id and empties),
  * validate(req)    -> a list of human-readable problems (basic shape checks),
  * build_example()  -> the worked two-group example (mirrors examples/*.yaml).

Design (see docs/SPEC.md): each GROUP is self-contained = one RDMP build.
inclusion is a CONTAINER (AND=INTERSECT / OR=UNION) built first; exclusions are
an ORDERED list subtracted in turn (root EXCEPT). Leaves are cohort sets of one
of four kinds: demographic / codes / sample / note.
"""
import uuid

PROJECT_TYPES = ["recruitment", "biobank"]
OPS = ["AND", "OR"]
KINDS = ["demographic", "codes", "sample", "note"]
EVENT_TYPES = ["hospitalisation", "medicine", "gp_data", "lab_result"]
# which code vocabulary the form shows for each event type
EVENT_VOCAB = {
    "hospitalisation": "ICD-10",
    "medicine": "BNF",
    "gp_data": "READ",
    "lab_result": "free text",
}
OCCURRENCE = ["first", "last"]
DIRECTION = ["before", "after"]
WITHIN_UNITS = ["days", "weeks", "months", "years"]
SCHEMA_VERSION = 1


def _id():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Node factories (UI-side nodes carry `_id`; stripped on export).
# ---------------------------------------------------------------------------
def new_container(op="AND", label="", members=None):
    return {"_id": _id(), "node": "container", "op": op, "label": label,
            "members": members if members is not None else []}


def new_demographic(label="", source="SHARE_Demography", age_min=None, age_max=None,
                    sex="both", residence="", simd=""):
    return {"_id": _id(), "node": "leaf", "kind": "demographic", "label": label,
            "source": source, "age_min": age_min, "age_max": age_max,
            "sex": sex, "residence": residence, "simd": simd}


def new_codes(label="", source="", icd=None, read=None, bnf=None, drug_names=None):
    return {"_id": _id(), "node": "leaf", "kind": "codes", "label": label, "source": source,
            "icd": icd or [], "read": read or [], "bnf": bnf or [], "drug_names": drug_names or []}


def new_sample(label="", event_type="gp_data", occurrence="first", event_label="",
               codes=None, direction="before", within=""):
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
    return {"project": "", "project_type": "biobank", "target_n": "", "ticket": "",
            "schema_version": SCHEMA_VERSION, "cohorts": [new_group("Group 1")]}


# ---------------------------------------------------------------------------
# Export: UI tree -> clean contract dict (strip _id / internal flags / empties).
# ---------------------------------------------------------------------------
def _clean(n):
    if n.get("node") == "container":
        out = {"op": n["op"]}
        if n.get("label"):
            out["label"] = n["label"]
        out["members"] = [_clean(m) for m in n.get("members", [])]
        return out
    k = n["kind"]
    out = {"kind": k}
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


def _build_member(d):
    """Inverse of _clean: a contract dict -> a UI node (with fresh _ids)."""
    if not isinstance(d, dict):
        return new_note("(unparseable)", str(d))
    if "op" in d or "members" in d:                       # container
        return new_container(d.get("op", "AND"), d.get("label", ""),
                             [_build_member(m) for m in d.get("members", [])])
    k = d.get("kind")
    if k == "demographic":
        return new_demographic(d.get("label", ""), d.get("source", "SHARE_Demography"),
                               d.get("age_min"), d.get("age_max"), d.get("sex", "both"),
                               d.get("residence", ""), d.get("simd", ""))
    if k == "codes":
        return new_codes(d.get("label", ""), d.get("source", ""), d.get("icd"),
                         d.get("read"), d.get("bnf"), d.get("drug_names"))
    if k == "sample":
        se = d.get("sample_event", {}) or {}
        ev = se.get("event", {}) or {}
        return new_sample(d.get("label", ""), ev.get("type", "gp_data"),
                          ev.get("occurrence", "first"), ev.get("label", ""),
                          ev.get("codes"), se.get("direction", "before"), se.get("within", ""))
    if k == "note":
        return new_note(d.get("label", ""), d.get("text", ""))
    return new_note(d.get("label", "(unknown)"), str(d))   # tolerate unknown kinds


def from_contract(data):
    """Load a requirement YAML/dict back into an editable UI tree."""
    data = data or {}
    req = {"project": data.get("project", ""),
           "project_type": data.get("project_type", "biobank"),
           "target_n": data.get("target_n", ""),
           "ticket": data.get("ticket", ""),
           "schema_version": data.get("schema_version", SCHEMA_VERSION),
           "cohorts": []}
    for gd in data.get("cohorts", []) or []:
        inc = _build_member(gd.get("inclusion") or {"op": "AND", "members": []})
        if inc.get("node") != "container":               # inclusion must be a container
            inc = new_container("AND", members=[inc])
        req["cohorts"].append({
            "_id": _id(), "name": gd.get("name", ""),
            "inclusion": inc,
            "exclusions": [_build_member(m) for m in (gd.get("exclusions") or [])]})
    if not req["cohorts"]:
        req["cohorts"] = [new_group("Group 1")]
    return req


def to_contract(req):
    out = {"project": req.get("project", ""),
           "project_type": req.get("project_type", ""),
           "target_n": req.get("target_n", ""),
           "schema_version": req.get("schema_version", SCHEMA_VERSION)}
    if req.get("ticket"):
        out["ticket"] = req["ticket"]
    out["cohorts"] = [{"name": g.get("name", ""),
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
            errs.append(f"{gname}: a {n.get('op', '?')} group has no members.")
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
        if project_type != "biobank":
            errs.append(f"{gname}: sample conditions are only valid for biobank projects.")
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
        errs.append("Project type must be recruitment or biobank.")
    if not req.get("cohorts"):
        errs.append("Add at least one group.")
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
# labels), so it does not resemble any real research request. It only shows the
# STRUCTURE: two self-contained groups, AND/OR nesting, a sample-event rule,
# and ordered exclusions.
# ---------------------------------------------------------------------------
def _condition_union():
    return new_container("OR", "Condition of interest (any source)", [
        new_codes("Condition in hospital data", "SMR01", icd=["A00"]),
        new_codes("Condition in GP data", "GP", read=["X1111"]),
    ])


def _adults():
    return new_demographic("Adults resident in Scotland", "SHARE_Demography",
                           age_min=18, age_max=80, sex="both", residence="Scotland", simd="any")


def build_example():
    req = new_requirement()
    req.update(project="Example cohort request (edit me)",
               project_type="biobank", target_n="approx. N per group", ticket="")

    a = new_group("Group A — cases")
    a["inclusion"] = new_container("AND", members=[
        _adults(),
        _condition_union(),
        new_container("OR", "A second condition (placeholder)", [
            new_codes("Second condition (GP READ)", "GP", read=["X2222"]),
            new_codes("Second condition (hospital ICD)", "SMR01", icd=["A01"]),
        ]),
        new_sample("Has a sample before first diagnosis",
                   event_type="gp_data", occurrence="first",
                   event_label="First recorded diagnosis", codes=["X1111"],
                   direction="before", within="6 months"),
    ])
    a["exclusions"] = [
        new_codes("Comorbidity to exclude", "SMR01", icd=["B00"]),
        new_note("Other criterion (no code yet)",
                 "Describe any criterion that has no agreed code."),
    ]

    b = new_group("Group B — controls")
    b["inclusion"] = new_container("AND", members=[
        _adults(),
        _condition_union(),
        new_sample("Has a sample after first diagnosis",
                   event_type="gp_data", occurrence="first",
                   event_label="First recorded diagnosis", codes=["X1111"],
                   direction="after", within="12 months"),
    ])
    b["exclusions"] = [
        new_codes("Exclude a condition variant", "GP", read=["X3333"]),
        new_codes("Comorbidity to exclude", "SMR01", icd=["B00"]),
    ]

    req["cohorts"] = [a, b]
    return req
