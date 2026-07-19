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
