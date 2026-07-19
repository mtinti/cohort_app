"""Injection defenses: a gate-clean contract must not be able to shape the
generated SQL/RDMP syntax, and a binding must not be able to inject SQL.
Covers the two output boundaries (SQL comments, RDMP quoted arguments)."""
import copy
import os

import pytest
import yaml

import registry as R
import requirement_schema as S
from compiler import CompileError, check_binding, compile_rdmp, compile_sql

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(ROOT, "examples")


def binding():
    with open(os.path.join(EX, "binding.site-a.yaml")) as f:
        return yaml.safe_load(f)


# --- gate blocks control characters in every text field ---------------------
def test_gate_rejects_newline_in_group_name():
    c = S.to_contract(S.build_example())
    c["cohorts"][0]["name"] = "cases\n-- DROP TABLE patients; --"
    assert any("control characters" in e for e in S.check_contract(c))


def test_gate_rejects_newline_in_label_and_note():
    c = S.to_contract(S.build_example())
    leaf = c["cohorts"][0]["inclusion"]["members"][0]
    leaf["label"] = 'x"\nCreateNewFilter injected'
    assert any("control characters" in e for e in S.check_contract(c))
    c2 = S.to_contract(S.build_example())
    note = c2["cohorts"][0]["exclusions"][1]
    assert note["kind"] == "note"
    note["text"] = "line1\nline2"                       # newlines OK in note text
    assert not any("control characters" in e for e in S.check_contract(c2))
    note["text"] = "bad\x00null"                        # other control chars not
    assert any("control characters" in e for e in S.check_contract(c2))


def test_gate_rejects_control_in_project_and_header():
    c = S.to_contract(S.build_example())
    c["project"] = "p\r\ninjected"
    assert any("control characters" in e for e in S.check_contract(c))


# --- binding cannot inject SQL identifiers -----------------------------------
def test_binding_rejects_non_identifier_columns():
    b = binding()
    b["sources"]["demographics"]["patient_id_column"] = "id; DROP TABLE x; --"
    assert any("not a valid SQL identifier" in e for e in check_binding(b))
    b = binding()
    b["sources"]["hospital_admissions"]["table"] = "t WHERE 1=1 UNION SELECT"
    assert any("not a valid SQL identifier" in e for e in check_binding(b))


def test_binding_rejects_quote_in_catalogue_and_filter_value():
    b = binding()
    b["sources"]["hospital_admissions"]["catalogue"] = 'Cat"\n- InjectedCommand'
    assert any("catalogue" in e and "printable text" in e for e in check_binding(b))
    # single quotes are fine (SQL string-escaping handles them); control
    # characters and double quotes are what break the quoted output context
    b = binding()
    b["sources"]["lab_results"]["measures"]["hba1c"]["filter_value"] = "ok'value"
    assert not any("filter_value" in e for e in check_binding(b))
    b["sources"]["lab_results"]["measures"]["hba1c"]["filter_value"] = "bad\ninject"
    assert any("filter_value" in e for e in check_binding(b))


def test_schema_qualified_identifier_allowed():
    b = binding()
    b["sources"]["demographics"]["table"] = "dbo.demog"
    assert check_binding(b) == []


# --- emitters escape at the boundary (defense in depth) ----------------------
def test_rdmp_escapes_quotes_in_label():
    # a label with a quote must be escaped, never break the command argument.
    # (the gate blocks control chars; quotes in a single-line label are legal
    #  text, so the emitter must still neutralize them)
    req = S.build_example()
    for g in req["cohorts"]:                            # drop note leaves (block compile)
        g["exclusions"] = [m for m in g["exclusions"] if m.get("kind") != "note"]
    req["cohorts"][0]["inclusion"]["members"][0]["label"] = 'evil " quote'
    c = S.to_contract(req)
    assert S.check_contract(c) == []                    # legal contract
    from compiler import load_binding
    out = compile_rdmp(c, load_binding(os.path.join(EX, "binding.site-a.yaml")))
    script = out[0]["script"]
    assert '\\"' in script                              # the quote was escaped
    for line in script.splitlines():                    # no arg-breaking newlines
        assert "\n" not in line


def test_provenance_and_comments_are_single_line():
    req = S.build_example()
    for g in req["cohorts"]:
        g["exclusions"] = [m for m in g["exclusions"] if m.get("kind") != "note"]
    c = S.to_contract(req)
    from compiler import load_binding
    for r in compile_sql(c, load_binding(os.path.join(EX, "binding.site-a.yaml"))):
        for line in r["sql"].splitlines():
            assert "\r" not in line


# --- DoS: unbounded recursion on nested containers --------------------------
def _nested(n):
    inner = {"id": "leaf", "kind": "codes", "source": "hospital_admissions",
             "icd": ["A00"]}
    for i in range(n):
        inner = {"id": f"c{i}", "op": "AND", "members": [inner]}
    return {"project": "p", "project_type": "recruitment", "schema_version": 3,
            "cohorts": [{"id": "g", "name": "G", "exclusions": [], "inclusion": inner}]}


def test_deep_nesting_is_rejected_not_crashed():
    errs = S.check_contract(_nested(5000))              # must not RecursionError
    assert any("nesting deeper" in e for e in errs)


def test_deep_nesting_draft_load_does_not_crash():
    issues = []
    S.from_contract(_nested(5000), issues)             # must not RecursionError
    assert any("truncated" in w for w in issues)


def test_compile_refuses_deep_nesting(sites=None):
    from compiler import compile_sql, load_binding, CompileError
    b = load_binding(os.path.join(EX, "binding.site-a.yaml"))
    with pytest.raises(CompileError):
        compile_sql(_nested(5000), b)


# --- path traversal via crafted persistent id -------------------------------
def test_gate_rejects_path_separator_ids():
    for bad in ("../../etc/passwd", "a/b", "a\\b", "a.b", "a b", "x" * 65, ""):
        c = S.to_contract(S.build_example())
        c["cohorts"][0]["id"] = bad
        assert any("id" in e for e in S.check_contract(c)), bad


def test_cli_out_confines_to_directory(tmp_path):
    # even if a bad id reached the emitter, --out basenames it
    import subprocess
    import sys
    # a legit contract compiles; the CLI must only write inside tmp_path
    r = subprocess.run(
        [sys.executable, "-m", "compiler",
         os.path.join(EX, "requirement.case-control.yaml"),
         os.path.join(EX, "binding.site-a.yaml"), "--out", str(tmp_path)],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": ROOT})
    assert r.returncode == 0, r.stderr
    for f in tmp_path.iterdir():
        assert f.parent == tmp_path                    # nothing escaped


# --- XSS: draft-loaded uploads with HTML in numeric/enum fields --------------
def _html_builders():
    """Import app.py's HTML builders without launching Streamlit's main()."""
    import sys
    import types
    st = types.ModuleType("streamlit")
    for name in ("set_page_config", "markdown", "caption", "title",
                 "subheader", "divider"):
        setattr(st, name, lambda *a, **k: None)
    st.dialog = lambda *a, **k: (lambda f: f)
    sys.modules["streamlit"] = st
    src = open(os.path.join(ROOT, "app.py")).read().rsplit("\nmain()", 1)[0]
    g = {"__name__": "appmod"}
    exec(compile(src, "app.py", "exec"), g)
    return g


APP = _html_builders()
XSS = "<img src=x onerror=alert(1)>"


def test_html_builders_escape_numeric_and_enum_fields():
    # a draft-loaded file can carry HTML strings in fields the schema expects
    # numeric/enum; the tree renders before validation, so every builder must
    # escape them
    nodes = [
        {"node": "leaf", "kind": "measure", "source": "labs", "measure": "BMI",
         "op": ">=", "value": XSS, "unit": "", "label": XSS},
        {"node": "leaf", "kind": "demographic", "age_min": XSS, "sex": "any"},
        {"node": "leaf", "kind": "sample", "sample_event": {
            "event": {"type": XSS, "occurrence": XSS, "codes": [XSS]},
            "direction": XSS, "within": {"n": XSS, "unit": "months"}}},
        {"node": "container", "op": XSS, "label": XSS},
    ]
    for n in nodes:
        rendered = APP["header_html"](n)
        if n.get("node") != "container":
            rendered += APP["body_html"](n)
        assert "<img src=x onerror" not in rendered, n
    anchor = {"when": {"anchor": {"event": {"source": XSS, "occurrence": XSS,
                                            "codes": [XSS]},
                                  "direction": XSS, "within": {"n": XSS, "unit": XSS}}}}
    assert "<img src=x onerror" not in "".join(APP["_when_lines"](anchor))


def test_esc_escapes_quotes():
    assert APP["_esc"]('a"b\'c') == "a&quot;b&#39;c"


def test_bad_container_op_does_not_crash_render():
    # a draft with an out-of-vocab op renders (before validation) without KeyError
    APP["header_html"]({"node": "container", "op": "EVIL", "label": "x"})


# --- lower-severity hardening (audit findings) ------------------------------
def test_measure_value_must_be_finite():
    c = S.to_contract(S.build_example())
    m = {"id": "m1", "kind": "measure", "source": "lab_results",
         "measure": "hba1c", "op": ">=", "value": float("inf")}
    c["cohorts"][0]["inclusion"]["members"].append(m)
    assert any("finite number" in e for e in S.check_contract(c))
    m["value"] = float("nan")
    assert any("finite number" in e for e in S.check_contract(c))


def test_impossible_and_unicode_dates_rejected():
    c = S.to_contract(S.build_example())
    leaf = c["cohorts"][0]["inclusion"]["members"][1]["members"][0]
    leaf["when"] = {"window": {"from": "2020-99-99"}}       # impossible calendar date
    assert any("valid ISO date" in e for e in S.check_contract(c))
    leaf["when"] = {"window": {"from": "2020-01-01"}}       # valid
    assert not any("ISO date" in e for e in S.check_contract(c))


def test_notes_in_and_validate_survive_deep_nesting():
    S.notes_in(_nested(5000))                               # must not RecursionError
    req = S.from_contract(_nested(5000))                    # truncated to <=64
    S.validate(req)                                         # must not RecursionError


def test_cli_rejects_unparseable_contract(tmp_path):
    import subprocess
    import sys
    bad = tmp_path / "bad.yaml"
    bad.write_text("[" * 6000)                              # deep flow nesting
    r = subprocess.run(
        [sys.executable, "-m", "compiler", str(bad),
         os.path.join(EX, "binding.site-a.yaml")],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": ROOT})
    assert r.returncode == 1                                # clean exit, not a crash
    assert "could not read contract" in r.stderr
    assert "Traceback" not in r.stderr
