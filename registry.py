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
import re

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))

# leaf field name in the YAML -> vocabulary id in the registry
VOCAB_FIELDS = {"icd": "icd10", "opcs": "opcs4", "read": "read", "bnf": "bnf",
                "drug_names": "drug_name"}
# sample_event event.type -> the logical source the event is read from
EVENT_SOURCE = {"hospitalisation": "hospital_admissions", "medicine": "prescribing",
                "gp_data": "gp_events", "lab_result": "lab_results"}
# sample_event event.type -> the vocabulary its codes are in (lab_result: free text)
EVENT_TYPE_VOCAB = {"hospitalisation": "icd10", "medicine": "bnf", "gp_data": "read"}


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


# --- controlled code FORMS (structure, not descriptions) ---------------------
_FORMS = {v: [re.compile(p) for p in spec.get("forms", [])]
          for v, spec in VOCABULARIES.items()}
_RANGE = re.compile(r"^([A-Z])([0-9]{2})-([A-Z])?([0-9]{2})$", re.IGNORECASE)


def normalize_code(vocab, code):
    """Apply the vocabulary's normalization (e.g. F02.3 -> F023)."""
    code = str(code).strip()
    if VOCABULARIES.get(vocab, {}).get("normalize") == "strip_dots":
        code = code.replace(".", "")
    return code


def invalid_code_forms(vocab, codes):
    """Codes that match NO allowed form for the vocabulary (or a bad range)."""
    forms = _FORMS.get(vocab, [])
    if not forms:                      # e.g. drug_name: any non-empty text
        return [c for c in codes if not str(c).strip()]
    bad = []
    for c in codes:
        c = str(c).strip()
        if not any(f.fullmatch(c) for f in forms):
            bad.append(c)
            continue
        m = _RANGE.match(c)
        if m:                          # range endpoints must be ordered
            lo = m.group(1).upper() + m.group(2)
            hi = (m.group(3) or m.group(1)).upper() + m.group(4)
            if hi < lo:
                bad.append(c)
    return bad


def vocabs_for(source):
    return SOURCES.get(source, {}).get("vocabularies", [])


def measures_for(source):
    return SOURCES.get(source, {}).get("measures", [])


def _check_forms(vocab, codes, where, errs):
    if not isinstance(codes, (list, tuple)):
        return                      # shape errors are the gate's job (level 1)
    bad = invalid_code_forms(vocab, [c for c in codes if isinstance(c, str)])
    if bad:
        label = VOCABULARIES.get(vocab, {}).get("label", vocab)
        hint = VOCABULARIES.get(vocab, {}).get("hint", "")
        msg = f"{where}: invalid {label} code(s): {', '.join(map(str, bad))}"
        if any(re.search(r"\s", str(b)) for b in bad):
            msg += (" (an entry contains whitespace — did several codes end up "
                    "in ONE entry? use one code per entry)")
        errs.append(msg + (f" — allowed: {hint}" if hint else ""))


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
    else:
        _check_forms(ev["vocab"], ev.get("codes"), where + " (anchor)", errs)


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
                if not d.get(field):
                    continue
                if vocab not in vocabs_for(src):
                    errs.append(f"{where}: vocabulary '{vocab}' ({field}) is not legal "
                                f"for source '{src}' (legal: {', '.join(vocabs_for(src))})")
                else:
                    _check_forms(vocab, d[field], where, errs)
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
            if ev.get("type") in EVENT_TYPE_VOCAB:
                _check_forms(EVENT_TYPE_VOCAB[ev["type"]], ev.get("codes"), where, errs)
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
