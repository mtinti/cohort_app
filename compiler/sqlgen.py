"""SQL emitter (SQLite-compatible) + the shared WHERE-builder.

Matching semantics come from the REGISTRY (prefix / exact_ci / range
expansion), never from the binding — the binding only supplies table and
column names. Every helper is fail-closed: anything it cannot prove it
supports raises CompileError instead of guessing.
"""
import re

import registry as R
import requirement_schema as S

from .binding import CompileError, src
from .feasibility import EVENT_TYPE_VOCAB
from .ir import DRAFT_BANNER, build_ir, oneline, precheck, provenance

_RANGE = re.compile(r"^([A-Z])([0-9]{2})-([A-Z])?([0-9]{2})$")


def _q(s):
    return "'" + str(s).replace("'", "''") + "'"


def _after(hi):
    """Exclusive upper bound of a 3-char block endpoint: D48->D49, D99->E00.
    None when there is nothing after (Z99)."""
    n = int(hi[1:]) + 1
    if n == 100:
        return None if hi[0] == "Z" else chr(ord(hi[0]) + 1) + "00"
    return f"{hi[0]}{n:02d}"


def match_atoms(vocab, codes):
    """Codes -> match atoms, per registry semantics: ('prefix'|'exact_ci', v)
    or ('span', lo, hi) for block ranges (F00-F09 / cross-letter C00-D48 —
    ICD-10 chapters cross letters, so spans compare strings, not prefixes)."""
    spec = R.VOCABULARIES.get(vocab)
    if spec is None:
        raise CompileError([f"unknown vocabulary '{vocab}'"])
    atoms = []
    for code in codes:
        code = R.normalize_code(vocab, code)
        m = _RANGE.match(code)
        if m:
            if spec.get("range") != "span":
                raise CompileError([f"vocabulary '{vocab}' does not support ranges; "
                                    f"cannot compile '{code}'"])
            lo = m.group(1) + m.group(2)
            hi = (m.group(3) or m.group(1)) + m.group(4)
            if hi < lo:
                raise CompileError([f"invalid range '{code}' (upper bound below lower)"])
            atoms.append(("span", lo, hi))
        elif "-" in code:
            raise CompileError([f"unsupported range syntax '{code}'"])
        else:
            atoms.append((spec["match"], code))
    return atoms


def _col_expr(column, vocab):
    """Registry-normative normalization on the DATA side too: with strip_dots,
    F02.3 and F023 in the column both match a contract code F02.3."""
    if R.VOCABULARIES.get(vocab, {}).get("normalize") == "strip_dots":
        return f"REPLACE({column}, '.', '')"
    return column


def code_clause(column, vocab, codes):
    col = _col_expr(column, vocab)
    parts = []
    for atom in match_atoms(vocab, codes):
        if atom[0] == "prefix":
            parts.append(f"{col} LIKE {_q(atom[1] + '%')}")
        elif atom[0] == "exact_ci":
            parts.append(f"LOWER({col}) = LOWER({_q(atom[1])})")
        elif atom[0] == "span":
            nxt = _after(atom[2])
            parts.append(f"({col} >= {_q(atom[1])} AND {col} < {_q(nxt)})" if nxt
                         else f"{col} >= {_q(atom[1])}")
        else:
            raise CompileError([f"unknown match mode '{atom[0]}'"])
    return "(" + " OR ".join(parts) + ")"


_UNIT_SQL = {"days": "days", "weeks": None, "months": "months", "years": "years"}


def _date_shift(base, sign, within):
    n, unit = within["n"], within["unit"]
    if unit == "weeks":                     # SQLite has no 'weeks' modifier
        n, unit = n * 7, "days"
    return f"date({base}, '{sign}{n} {unit}')"


def _index_subquery(anchor_event, binding, outer_pid):
    """Scalar subquery: this patient's index date (first/last coded event)."""
    esrc = anchor_event["source"]
    esb = src(binding, esrc)
    agg = "MIN" if anchor_event.get("occurrence", "first") == "first" else "MAX"
    clause = code_clause("e." + esb["code_columns"][anchor_event["vocab"]],
                         anchor_event["vocab"], anchor_event["codes"])
    return (f"(SELECT {agg}(e.{esb['date_column']}) FROM {esb['table']} e "
            f"WHERE e.{esb['patient_id_column']} = {outer_pid} AND {clause})")


def _anchor_clause(anchor, binding, date_col, outer_pid):
    idx = _index_subquery(anchor["event"], binding, outer_pid)
    within = anchor.get("within")
    if anchor["direction"] == "before":
        cl = f"{date_col} < {idx}"
        if within:
            cl += f" AND {date_col} >= {_date_shift(idx, '-', within)}"
    else:
        cl = f"{date_col} > {idx}"
        if within:
            cl += f" AND {date_col} <= {_date_shift(idx, '+', within)}"
    return cl


def _when_clauses(leaf, sb, binding, alias="t"):
    w = leaf.get("when") or {}
    date_col = f"{alias}.{sb['date_column']}" if (w.get("window") or w.get("anchor")) else None
    out = []
    win = w.get("window") or {}
    if win.get("from"):
        out.append(f"{date_col} >= {_q(win['from'])}")
    if win.get("to"):
        out.append(f"{date_col} <= {_q(win['to'])}")
    if w.get("anchor"):
        out.append(_anchor_clause(w["anchor"], binding, date_col,
                                  f"{alias}.{sb['patient_id_column']}"))
    return out


def leaf_where(leaf, binding, alias="t"):
    """WHERE clauses for one leaf (shared by the SQL and RDMP emitters)."""
    k = leaf["kind"]
    sb = src(binding, leaf.get("source", ""))
    a = alias + "." if alias else ""
    if k == "demographic":
        cols = sb.get("columns") or {}
        out = []
        if leaf.get("age_min") is not None:
            out.append(f"{a}{cols['age']} >= {int(leaf['age_min'])}")
        if leaf.get("age_max") is not None:
            out.append(f"{a}{cols['age']} <= {int(leaf['age_max'])}")
        if leaf.get("sex") in ("female", "male"):
            out.append(f"{a}{cols['sex']} = {_q(leaf['sex'])}")
        for f in ("residence", "simd"):
            if leaf.get(f):
                raise CompileError([f"criterion {leaf.get('id')}: '{f}' is not compilable"])
        return out or ["1=1"]
    if k == "codes":
        vocab_parts = [code_clause(f"{a}{sb['code_columns'][vocab]}", vocab, leaf[field])
                       for field, vocab in R.VOCAB_FIELDS.items() if leaf.get(field)]
        return ["(" + " OR ".join(vocab_parts) + ")"] + _when_clauses(leaf, sb, binding, alias)
    if k == "measure":
        spec = sb["measures"][leaf["measure"]]
        out = []
        if spec.get("filter_column"):
            out.append(f"{a}{spec['filter_column']} = {_q(spec['filter_value'])}")
        op = leaf["op"]
        out.append(f"{a}{spec['value_column']} {op} {leaf['value']}")
        return out + _when_clauses(leaf, sb, binding, alias)
    if k == "sample":
        se = leaf["sample_event"]
        ev = se["event"]
        ssb = src(binding, "biobank_samples")
        anchor = {"event": {"source": R.EVENT_SOURCE[ev["type"]],
                            "vocab": EVENT_TYPE_VOCAB[ev["type"]],
                            "codes": ev["codes"],
                            "occurrence": ev.get("occurrence", "first")},
                  "direction": se["direction"], "within": se.get("within")}
        return [_anchor_clause(anchor, binding, f"{a}{ssb['date_column']}",
                               f"{a}{ssb['patient_id_column']}")]
    raise CompileError([f"criterion {leaf.get('id')}: kind '{k}' is not compilable"])


def _leaf_sql(leaf, binding):
    source = "biobank_samples" if leaf["kind"] == "sample" else leaf["source"]
    sb = src(binding, source)
    where = " AND ".join(leaf_where(leaf, binding))
    return (f"SELECT DISTINCT t.{sb['patient_id_column']} AS patient_id\n"
            f"FROM {sb['table']} t\nWHERE {where}")


def _emit(expr, binding):
    kind = expr[0]
    if kind == "leaf":
        return _leaf_sql(expr[1], binding)
    if kind in ("and", "or"):
        op = "INTERSECT" if kind == "and" else "UNION"
        parts = [f"SELECT patient_id FROM (\n{_emit(c, binding)}\n)" for c in expr[1]]
        return f"\n{op}\n".join(parts)
    if kind == "except":
        base = f"SELECT patient_id FROM (\n{_emit(expr[1], binding)}\n)"
        for e in expr[2]:                     # subtracted IN ORDER
            base += f"\nEXCEPT\nSELECT patient_id FROM (\n{_emit(e, binding)}\n)"
        return base
    raise CompileError([f"unknown IR node '{kind}'"])


def compile_sql(contract, binding, draft=False):
    """[{id, name, sql}] — one SQL script per cohort group."""
    precheck(contract, binding, draft=draft)
    out = []
    for g in build_ir(contract):
        head = ""
        if draft and S.notes_in(contract):
            head = DRAFT_BANNER + "\n"
        head += (f"-- cohort group: {oneline(g['name'])} (id {oneline(g['id'])})\n"
                 f"-- {provenance(contract, binding)}\n")
        expr = g["expr"]
        if not expr[2]:                       # no exclusions -> no EXCEPT chain
            expr = expr[1]
        sql = _emit(_strip_notes(expr) if draft else expr, binding)
        out.append({"id": g["id"], "name": g["name"], "sql": head + sql + ";\n"})
    return out


def _strip_notes(expr):
    """Draft mode only: drop note leaves (the banner makes output non-runnable)."""
    kind = expr[0]
    if kind == "leaf":
        return expr
    if kind in ("and", "or"):
        kept = [_strip_notes(c) for c in expr[1]
                if not (c[0] == "leaf" and c[1].get("kind") == "note")]
        return (kind, kept)
    return ("except", _strip_notes(expr[1]),
            [_strip_notes(e) for e in expr[2]
             if not (e[0] == "leaf" and e[1].get("kind") == "note")])
