"""Logical source registry — loader and level-2 (registry conformance) checks.

`sources.yaml` is the controlled vocabulary contracts reference, and it is
NORMATIVE for meaning: code-matching / range-expansion semantics are defined
here, never per site. Site bindings (binding.<site>.yaml) only map these
logical names to local tables/columns.

check_sources(contract) is validation LEVEL 2 (see plan.md §3.4): given a raw
contract dict, is every source known and every vocabulary/measure legal for
its source? Level 1 (shape) is requirement_schema.check_contract; level 3
(per-site feasibility) is compiler.feasibility.
"""
import os

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))

# leaf field name in the YAML -> vocabulary id in the registry
VOCAB_FIELDS = {"icd": "icd10", "read": "read", "bnf": "bnf", "drug_names": "drug_name"}
# sample_event event.type -> the logical source the event is read from
EVENT_SOURCE = {"hospitalisation": "hospital_admissions", "medicine": "prescribing",
                "gp_data": "gp_events", "lab_result": "lab_results"}


def load_registry(path=None):
    with open(path or os.path.join(ROOT, "sources.yaml")) as f:
        return yaml.safe_load(f)


REGISTRY = load_registry()
VOCABULARIES = REGISTRY["vocabularies"]
SOURCES = REGISTRY["sources"]
REGISTRY_VERSION = REGISTRY["registry_version"]


def sources_for(kind):
    """Logical source names whose registry entry allows this criterion kind."""
    return [name for name, s in SOURCES.items() if kind in s.get("kinds", [])]


def vocabs_for(source):
    return SOURCES.get(source, {}).get("vocabularies", [])


def measures_for(source):
    return SOURCES.get(source, {}).get("measures", [])


def _check_anchor(a, where, errs):
    ev = (a or {}).get("event") or {}
    src = ev.get("source")
    if src not in SOURCES:
        errs.append(f"{where}: anchor event source {src!r} is not in the registry")
    elif "anchor" not in SOURCES[src].get("kinds", []):
        errs.append(f"{where}: source '{src}' cannot be used as an anchor event")
    elif ev.get("vocab") not in vocabs_for(src):
        errs.append(f"{where}: vocabulary {ev.get('vocab')!r} is not legal for "
                    f"anchor source '{src}' (legal: {', '.join(vocabs_for(src)) or 'none'})")


def check_sources(contract):
    """LEVEL 2: registry conformance of a raw contract dict. [] = conforms.

    Tolerant of shape problems (level 1 reports those); only checks
    source/vocabulary/measure legality where the fields are present.
    """
    errs = []

    def leaf(d, where):
        k = d.get("kind")
        src = d.get("source")
        if k in ("demographic", "codes", "measure"):
            if src not in SOURCES:
                errs.append(f"{where}: source {src!r} is not in the registry "
                            f"(known: {', '.join(SOURCES)})")
                return
            if k not in SOURCES[src].get("kinds", []):
                errs.append(f"{where}: source '{src}' does not support kind '{k}' "
                            f"(supports: {', '.join(SOURCES[src].get('kinds', []))})")
                return
        if k == "codes":
            for field, vocab in VOCAB_FIELDS.items():
                if d.get(field) and vocab not in vocabs_for(src):
                    errs.append(f"{where}: vocabulary '{vocab}' ({field}) is not legal "
                                f"for source '{src}' (legal: {', '.join(vocabs_for(src))})")
        elif k == "measure":
            if d.get("measure") not in measures_for(src):
                errs.append(f"{where}: measure {d.get('measure')!r} is not defined for "
                            f"source '{src}' (defined: {', '.join(measures_for(src)) or 'none'})")
        elif k == "sample":
            ev = (d.get("sample_event") or {}).get("event") or {}
            if ev.get("type") in EVENT_SOURCE and EVENT_SOURCE[ev["type"]] not in SOURCES:
                errs.append(f"{where}: event type '{ev.get('type')}' maps to a source "
                            "missing from the registry")
            if "biobank_samples" not in SOURCES:
                errs.append(f"{where}: registry has no 'biobank_samples' source")
        if isinstance(d.get("when"), dict) and d["when"].get("anchor"):
            _check_anchor(d["when"]["anchor"], where, errs)

    def member(d, where):
        if not isinstance(d, dict):
            return
        if d.get("kind"):                 # a leaf always carries `kind`
            leaf(d, where)
        elif "op" in d or "members" in d:
            for j, m in enumerate(d.get("members") or [], 1):
                member(m, f"{where} > member {j}")

    for gi, g in enumerate((contract or {}).get("cohorts") or [], 1):
        if not isinstance(g, dict):
            continue
        gname = g.get("name") or f"group {gi}"
        if isinstance(g.get("inclusion"), dict):
            member(g["inclusion"], f"{gname} inclusion")
        for j, m in enumerate(g.get("exclusions") or [], 1):
            member(m, f"{gname} exclusion {j}")
    return errs
