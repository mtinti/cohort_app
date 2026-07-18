"""Schema unit tests (no browser): validation, round-trip, coverage."""
import yaml

import requirement_schema as S


def test_example_is_valid():
    assert S.validate(S.build_example()) == []


def test_blank_requirement_is_invalid():
    errs = S.validate(S.new_requirement())
    assert any("Project title" in e for e in errs)
    assert any("inclusion must have at least one condition" in e for e in errs)


def test_roundtrip_stable():
    c = S.to_contract(S.build_example())
    reloaded = yaml.safe_load(yaml.dump(c, sort_keys=False, allow_unicode=True))
    assert reloaded == c


def test_contract_strips_internal_ids():
    text = yaml.dump(S.to_contract(S.build_example()))
    assert "_id" not in text and "node:" not in text


def _walk_members(n):
    yield n
    for m in n.get("members", []):
        yield from _walk_members(m)


def test_contract_has_persistent_ids():
    # every group, container and leaf carries a persistent id in the export
    c = S.to_contract(S.build_example())
    for g in c["cohorts"]:
        assert g["id"]
        for n in list(_walk_members(g["inclusion"])) + [x for m in g["exclusions"]
                                                        for x in _walk_members(m)]:
            assert n["id"], n


def test_ids_survive_roundtrip():
    c = S.to_contract(S.build_example())
    c2 = S.to_contract(S.from_contract(c))
    assert c2 == c                                  # ids included


def test_validate_codes_without_codes():
    req = S.new_requirement()
    req["project"] = "x"
    req["cohorts"][0]["inclusion"]["members"].append(S.new_codes("empty", "GP"))
    assert any("has no codes" in e for e in S.validate(req))


def test_validate_age_order():
    req = S.new_requirement()
    req["project"] = "x"
    req["cohorts"][0]["inclusion"]["members"].append(
        S.new_demographic("bad age", age_min=80, age_max=18))
    assert any("age_min > age_max" in e for e in S.validate(req))


def test_every_kind_constructs_and_exports():
    for k in S.KINDS:
        leaf = S.new_leaf(k, f"a {k}")
        cleaned = S._clean(leaf)
        assert cleaned["kind"] == k


def test_schema_is_flag_independent():
    # ONE SCHEMA EVERYWHERE: the flag never changes what the schema accepts
    assert S.KINDS == ["demographic", "codes", "measure", "sample", "note"]
    assert "biobank" in S.PROJECT_TYPES
    # …it only gates what the UI offers (default OFF = general builder)
    assert "sample" not in S.UI_KINDS
    assert "biobank" not in S.UI_PROJECT_TYPES


def test_flag_widens_ui_only():
    # COHORT_ENABLE_SAMPLES=1 surfaces the sample kind + biobank type in the UI
    # lists; the normative schema stays identical (checked in a clean subprocess)
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import requirement_schema as S;"
            "assert 'sample' in S.UI_KINDS;"
            "assert 'biobank' in S.UI_PROJECT_TYPES;"
            "assert S.KINDS == ['demographic', 'codes', 'measure', 'sample', 'note'];"
            "assert S.PROJECT_TYPES == ['recruitment', 'registry', 'biobank', 'other'];"
            "assert S.validate(S.build_example()) == [];"
            "print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=root,
                       env={**os.environ, "COHORT_ENABLE_SAMPLES": "1"},
                       capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


def test_sample_kind_not_coerced_when_flag_off():
    # a sample condition in a loaded contract stays a sample (semantic
    # preservation) even though the default UI doesn't offer creating one
    contract = {"project": "x", "project_type": "recruitment",
                "schema_version": S.SCHEMA_VERSION,
                "cohorts": [{"id": "g1", "name": "G", "exclusions": [], "inclusion": {
                    "id": "c1", "op": "AND", "members": [
                        {"id": "s1", "kind": "sample", "label": "has sample",
                         "sample_event": {"event": {"type": "gp_data", "occurrence": "first",
                                                    "codes": ["X1"]},
                                          "direction": "before"}}]}}]}
    issues = []
    req = S.from_contract(contract, issues)
    leaf = req["cohorts"][0]["inclusion"]["members"][0]
    assert leaf["kind"] == "sample" and leaf["_id"] == "s1"
    assert issues == []                             # nothing was coerced
    assert S.check_contract(contract) == []         # and it passes the gate


def test_from_contract_roundtrip():
    ex = S.build_example()
    rebuilt = S.from_contract(S.to_contract(ex))
    assert S.to_contract(rebuilt) == S.to_contract(ex)     # load->export equals original export


def test_from_contract_tolerates_empty():
    req = S.from_contract({})
    assert req["cohorts"] and S.validate(req)               # has a default group, but invalid (blank)


def test_clone_group_fresh_ids_same_content():
    g = S.build_example()["cohorts"][0]
    clone = S.clone_group(g)

    def ids(node, acc):
        acc.append(node["_id"])
        if node.get("node") == "container":
            for m in node["members"]:
                ids(m, acc)
        return acc
    orig_ids = ids(g["inclusion"], [g["_id"]]) + sum((ids(m, []) for m in g["exclusions"]), [])
    new_ids = ids(clone["inclusion"], [clone["_id"]]) + sum((ids(m, []) for m in clone["exclusions"]), [])
    assert set(orig_ids).isdisjoint(new_ids)            # no shared ids
    # content identical except the renamed group and the fresh persistent ids
    gc, cc = S.to_contract({"project": "x", "project_type": "biobank", "cohorts": [g]}), \
        S.to_contract({"project": "x", "project_type": "biobank", "cohorts": [clone]})
    assert clone["name"] == g["name"] + " (copy)"
    gc["cohorts"][0]["name"] = cc["cohorts"][0]["name"]

    def strip_ids(o):
        if isinstance(o, dict):
            return {k: strip_ids(v) for k, v in o.items() if k != "id"}
        if isinstance(o, list):
            return [strip_ids(v) for v in o]
        return o
    assert strip_ids(gc) == strip_ids(cc)


# ---------------------------------------------------------------------------
# Strict gate (fail-closed) vs draft load (tolerant but reported)
# ---------------------------------------------------------------------------
def _minimal_contract():
    return {"project": "x", "project_type": "recruitment", "target_n": "",
            "schema_version": S.SCHEMA_VERSION,
            "cohorts": [{"id": "g1", "name": "G", "exclusions": [], "inclusion": {
                "id": "c1", "op": "AND", "members": [
                    {"id": "l1", "kind": "codes", "label": "c",
                     "source": "hospital_admissions", "icd": ["A00"]}]}}]}


def test_gate_accepts_app_export():
    assert S.check_contract(S.to_contract(S.build_example())) == []
    assert S.check_contract(_minimal_contract()) == []


def test_gate_rejects_unsupported_version():
    c = _minimal_contract()
    c["schema_version"] = 99
    assert any("schema_version" in e for e in S.check_contract(c))
    c["schema_version"] = None
    assert any("schema_version" in e for e in S.check_contract(c))


def test_gate_rejects_unknown_kind():
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["members"].append(
        {"id": "l2", "kind": "genomic_variant", "label": "future thing"})
    assert any("unknown kind 'genomic_variant'" in e for e in S.check_contract(c))


def test_gate_rejects_unknown_fields():
    c = _minimal_contract()
    c["surprise"] = True
    c["cohorts"][0]["inclusion"]["members"][0]["snomed"] = ["123"]
    errs = S.check_contract(c)
    assert any("top level: unknown field(s): surprise" in e for e in errs)
    assert any("snomed" in e for e in errs)


def test_gate_rejects_missing_and_duplicate_ids():
    c = _minimal_contract()
    del c["cohorts"][0]["inclusion"]["members"][0]["id"]
    assert any("missing persistent id" in e for e in S.check_contract(c))
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["id"] = "g1"           # collides with the group
    assert any("duplicate id 'g1'" in e for e in S.check_contract(c))


def test_gate_rejects_bad_project_type_and_op():
    c = _minimal_contract()
    c["project_type"] = "campaign"
    c["cohorts"][0]["inclusion"]["op"] = "XOR"
    errs = S.check_contract(c)
    assert any("project_type" in e for e in errs)
    assert any("XOR" in e for e in errs)


def test_draft_load_reports_never_silent():
    # unknown kind survives VISIBLY as a note AND the coercion is reported
    c = _minimal_contract()
    c["schema_version"] = 99
    c["cohorts"][0]["inclusion"]["members"].append(
        {"id": "l2", "kind": "genomic_variant", "label": "future thing"})
    issues = []
    req = S.from_contract(c, issues)
    kinds = [m["kind"] for m in req["cohorts"][0]["inclusion"]["members"]]
    assert kinds == ["codes", "note"]
    assert any("unknown kind 'genomic_variant'" in w for w in issues)
    assert any("schema_version 99" in w for w in issues)


def test_draft_load_clean_file_reports_nothing():
    issues = []
    S.from_contract(_minimal_contract(), issues)
    assert issues == []


def test_duplicate_group_names_invalid():
    req = S.from_contract(_minimal_contract())
    req["cohorts"].append(S.clone_group(req["cohorts"][0]))
    req["cohorts"][1]["name"] = req["cohorts"][0]["name"]
    assert any("used more than once" in e for e in S.validate(req))


# ---------------------------------------------------------------------------
# v2: measure kind, timing (`when`), legacy coercions, contract header + hash
# ---------------------------------------------------------------------------
def test_measure_gate_checks():
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["members"].append(
        {"id": "m1", "kind": "measure", "source": "lab_results",
         "measure": "hba1c", "op": ">=", "value": 48})
    assert S.check_contract(c) == []
    c["cohorts"][0]["inclusion"]["members"][1]["op"] = "~"
    c["cohorts"][0]["inclusion"]["members"][1]["value"] = "high"
    errs = S.check_contract(c)
    assert any("measure op" in e for e in errs)
    assert any("must be a number" in e for e in errs)


def test_when_gate_checks():
    c = _minimal_contract()
    leaf = c["cohorts"][0]["inclusion"]["members"][0]
    leaf["when"] = {"window": {"from": "2018-01-01", "to": "2020-12-31"}}
    assert S.check_contract(c) == []
    leaf["when"] = {"window": {"from": "whenever"}}
    assert any("ISO date" in e for e in S.check_contract(c))
    leaf["when"] = {"anchor": {"event": {"source": "gp_events", "vocab": "read",
                                         "codes": ["X1"], "occurrence": "first"},
                               "direction": "before",
                               "within": {"n": 6, "unit": "months"}}}
    assert S.check_contract(c) == []
    leaf["when"]["anchor"]["within"] = {"n": 0, "unit": "fortnights"}
    errs = S.check_contract(c)
    assert any("positive integer" in e for e in errs)
    assert any("within.unit" in e for e in errs)
    leaf["when"] = {}
    assert any("window and/or an anchor" in e for e in S.check_contract(c))


def test_draft_load_coerces_legacy_sex_and_within():
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["members"] = [
        {"id": "d1", "kind": "demographic", "sex": "both", "age_min": 18},
        {"id": "s1", "kind": "sample",
         "sample_event": {"event": {"type": "gp_data", "codes": ["X1"]},
                          "direction": "before", "within": "6 months"}}]
    issues = []
    req = S.from_contract(c, issues)
    d, s = req["cohorts"][0]["inclusion"]["members"]
    assert d["sex"] == "any"
    assert s["sample_event"]["within"] == {"n": 6, "unit": "months"}
    assert any("legacy sex 'both'" in w for w in issues)
    assert any("legacy within '6 months'" in w for w in issues)


def test_seal_and_hash_detects_edits():
    req = S.build_example()
    assert S.hash_status(S.to_contract(req)) is None        # unsealed
    S.seal(req, approved_by="reviewer")
    c = S.to_contract(req)
    assert c["contract"]["status"] == "agreed"
    assert S.hash_status(c) == "ok"
    assert S.check_contract(c) == []
    c["cohorts"][0]["name"] = "tampered"                    # edit after approval
    assert S.hash_status(c) == "changed"
    assert any("CHANGED since it was sealed" in e for e in S.check_contract(c))


def test_gate_rejects_bad_header():
    c = _minimal_contract()
    c["contract"] = {"status": "signed", "notary": "x"}
    errs = S.check_contract(c)
    assert any("contract.status" in e for e in errs)
    assert any("notary" in e for e in errs)
    c["contract"] = {"status": "agreed"}                    # agreed needs id + hash
    errs = S.check_contract(c)
    assert any("contract.id" in e for e in errs)
    assert any("contract.body_sha256" in e for e in errs)


def test_seal_roundtrips_through_yaml():
    req = S.build_example()
    S.seal(req)
    text = yaml.dump(S.to_contract(req), sort_keys=False, allow_unicode=True)
    reloaded = yaml.safe_load(text)
    assert S.hash_status(reloaded) == "ok"
    issues = []
    req2 = S.from_contract(reloaded, issues)
    assert issues == []
    assert S.hash_status(S.to_contract(req2)) == "ok"       # survives load/export


def test_json_schema_file_in_sync():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "requirement.schema.json")) as f:
        assert json.load(f) == S.json_schema()


def test_json_schema_validates_example():
    jsonschema = __import__("pytest").importorskip("jsonschema")
    jsonschema.validate(S.to_contract(S.build_example()), S.json_schema())


def test_validation_paths_point_to_position():
    req = S.from_contract(_minimal_contract())
    req["cohorts"][0]["inclusion"]["members"].append(
        S.new_container("OR", members=[S.new_container("AND")]))   # empty, nested
    req["cohorts"][0]["exclusions"].append(S.new_container("OR"))  # empty, top-level
    errs = S.validate(req)
    assert any("G › inclusion 2.1: this INTERSECT (all of) container is empty" in e
               for e in errs)
    assert any("G › exclusion 1: this UNION (any of) container is empty" in e
               for e in errs)


def test_notes_in_reports_positions():
    c = S.to_contract(S.build_example())
    notes = S.notes_in(c)
    assert len(notes) == 1
    nid, lbl, where = notes[0]
    assert where == "Group A — cases › exclusion 2"
    assert lbl == "Other criterion (no code yet)"


# ---------------------------------------------------------------------------
# Review findings on the controlled-forms change (db54909)
# ---------------------------------------------------------------------------
def test_schema_v3_and_v2_files_draft_upgrade():
    assert S.SCHEMA_VERSION == 3            # opcs made v2 ambiguous -> bumped
    c = _minimal_contract()
    c["schema_version"] = 2
    assert any("schema_version" in e for e in S.check_contract(c))
    issues = []
    req = S.from_contract(c, issues)        # migration: draft-load upgrades
    assert any("UPGRADED to v3" in w for w in issues)
    upgraded = S.to_contract(req)
    assert upgraded["schema_version"] == 3
    assert S.check_contract(upgraded) == []


def test_gate_rejects_non_list_code_fields():
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["members"][0]["icd"] = 123
    assert any("icd must be a non-empty list of code strings" in e
               for e in S.check_contract(c))
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["members"][0]["icd"] = ["A00", 5]
    assert any("list of code strings" in e for e in S.check_contract(c))
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["members"][0]["when"] = {
        "anchor": {"event": {"source": "gp_events", "vocab": "read",
                             "codes": "X1111"},          # string, not list
                   "direction": "before"}}
    assert any("anchor.event.codes" in e for e in S.check_contract(c))


def test_registry_tolerates_shape_errors():
    import registry as RG
    c = _minimal_contract()
    c["cohorts"][0]["inclusion"]["members"][0]["icd"] = 123
    RG.check_sources(c)                     # must not raise (gate reports shape)
    c["cohorts"][0]["inclusion"]["members"][0]["icd"] = ["A00", None]
    RG.check_sources(c)


def test_new_codes_vocab_args_are_keyword_only():
    import pytest
    with pytest.raises(TypeError):
        S.new_codes("label", "hospital_admissions", ["A00"])


# ---------------------------------------------------------------------------
# Review round 2 on the controlled-forms fixes (fb5a4a9)
# ---------------------------------------------------------------------------
def test_gate_requires_at_least_one_code_field():
    c = _minimal_contract()
    leaf = c["cohorts"][0]["inclusion"]["members"][0]
    del leaf["icd"]                                     # no code fields at all
    assert any("needs at least one of" in e for e in S.check_contract(c))
    leaf["icd"] = None                                  # explicit null = typed error
    assert any("icd must be a non-empty list" in e for e in S.check_contract(c))


def test_gate_requires_codes_for_coded_sample_events():
    def sample(codes_value, etype="gp_data"):
        se = {"event": {"type": etype, "occurrence": "first"},
              "direction": "before"}
        if codes_value != "ABSENT":
            se["event"]["codes"] = codes_value
        return {"project": "x", "project_type": "recruitment",
                "schema_version": S.SCHEMA_VERSION,
                "cohorts": [{"id": "g", "name": "G", "exclusions": [], "inclusion": {
                    "id": "c", "op": "AND", "members": [
                        {"id": "s", "kind": "sample", "sample_event": se}]}}]}
    assert any("non-empty list" in e for e in S.check_contract(sample("ABSENT")))
    assert any("non-empty list" in e for e in S.check_contract(sample([])))
    assert S.check_contract(sample(["X1111"])) == []
    # lab_result is free text: absent/empty codes are fine
    assert S.check_contract(sample("ABSENT", etype="lab_result")) == []
    assert S.check_contract(sample([], etype="lab_result")) == []


def test_unknown_future_versions_are_not_relabelled():
    c = _minimal_contract()
    c["schema_version"] = 99
    issues = []
    req = S.from_contract(c, issues)
    assert any("kept as-is" in w for w in issues)
    exported = S.to_contract(req)
    assert exported["schema_version"] == 99             # NOT silently upgraded
    assert any("schema_version" in e for e in S.check_contract(exported))


def test_json_schema_rejects_blank_code_strings():
    jsonschema = __import__("pytest").importorskip("jsonschema")
    c = S.to_contract(S.build_example())
    jsonschema.validate(c, S.json_schema())
    c["cohorts"][0]["inclusion"]["members"][1]["members"][0]["icd"] = ["   "]
    with __import__("pytest").raises(jsonschema.ValidationError):
        jsonschema.validate(c, S.json_schema())
    assert S.check_contract(c) != []                    # python agrees


def test_fixture_ids_are_stable():
    # persistent ids must survive schema-version bumps (they address criteria
    # in reviews/diffs); pin a few from the committed fixtures
    import os
    import yaml as _y
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cc = _y.safe_load(open(os.path.join(root, "examples/requirement.case-control.yaml")))
    assert cc["cohorts"][0]["id"] == "65080a14"
    assert cc["cohorts"][0]["inclusion"]["members"][0]["id"] == "d6e1b524"


# ---------------------------------------------------------------------------
# Review round 3 (072c685): python/JSON-Schema agreement + version typing
# ---------------------------------------------------------------------------
def _leaf_contract(leaf):
    return {"project": "x", "project_type": "recruitment",
            "schema_version": S.SCHEMA_VERSION,
            "cohorts": [{"id": "g", "name": "G", "exclusions": [], "inclusion": {
                "id": "c", "op": "AND", "members": [leaf]}}]}


def test_python_and_json_schema_agree_on_code_criteria():
    jsonschema = __import__("pytest").importorskip("jsonschema")
    schema = S.json_schema()

    def js_ok(c):
        try:
            jsonschema.validate(c, schema)
            return True
        except jsonschema.ValidationError:
            return False

    cases = [
        ({"id": "l", "kind": "codes", "source": "hospital_admissions"}, False),
        ({"id": "l", "kind": "codes", "source": "hospital_admissions",
          "icd": None}, False),
        ({"id": "l", "kind": "codes", "source": "hospital_admissions",
          "icd": ["A00"], "opcs": None}, False),         # explicit null rejected
        ({"id": "l", "kind": "codes", "source": "hospital_admissions",
          "icd": ["A00"]}, True),
        ({"id": "l", "kind": "sample", "sample_event": {
            "event": {"type": "gp_data", "occurrence": "first"},
            "direction": "before"}}, False),             # coded event, no codes
        ({"id": "l", "kind": "sample", "sample_event": {
            "event": {"type": "gp_data", "occurrence": "first", "codes": []},
            "direction": "before"}}, False),
        ({"id": "l", "kind": "sample", "sample_event": {
            "event": {"type": "gp_data", "occurrence": "first", "codes": ["X1111"]},
            "direction": "before"}}, True),
        ({"id": "l", "kind": "sample", "sample_event": {
            "event": {"type": "lab_result", "occurrence": "first"},
            "direction": "before"}}, True),              # free text: codes optional
    ]
    for leaf, expected in cases:
        c = _leaf_contract(leaf)
        py = S.check_contract(c) == []
        js = js_ok(c)
        assert py == js == expected, (leaf, py, js, expected)


def test_malformed_schema_versions_never_crash_or_pass():
    for sv in ([], {}, True, False, "3"):
        c = _minimal_contract()
        c["schema_version"] = sv
        issues = []
        req = S.from_contract(c, issues)                # must not raise
        assert any("schema_version" in w for w in issues)
        assert S.to_contract(req)["schema_version"] == sv   # never relabelled
        assert any("schema_version" in e for e in S.check_contract(c))
    # bool True must not be treated as migratable v1 (True == 1 in python)
    c = _minimal_contract()
    c["schema_version"] = True
    issues = []
    S.from_contract(c, issues)
    assert any("kept as-is" in w for w in issues)


def test_integral_float_versions_match_json_semantics():
    # JSON has one number type: 3.0 IS 3 there, so python agrees (and
    # canonicalizes on load); 2.0 migrates like 2; bools stay excluded
    c = _minimal_contract()
    c["schema_version"] = 3.0
    assert S.check_contract(c) == []
    issues = []
    req = S.from_contract(c, issues)
    assert any("canonicalized to 3" in w for w in issues)
    assert S.to_contract(req)["schema_version"] == 3
    c["schema_version"] = 2.0
    issues = []
    req = S.from_contract(c, issues)
    assert any("UPGRADED to v3" in w for w in issues)
    assert S.to_contract(req)["schema_version"] == 3


def test_python_and_json_schema_agree_on_versions():
    jsonschema = __import__("pytest").importorskip("jsonschema")
    schema = S.json_schema()
    for sv in (3, 3.0, 2, True, "3", None):
        c = _minimal_contract()
        c["schema_version"] = sv
        py = S.check_contract(c) == []
        try:
            jsonschema.validate(c, schema)
            js = True
        except jsonschema.ValidationError:
            js = False
        assert py == js, (sv, py, js)


def test_huge_integer_versions_do_not_crash():
    c = _minimal_contract()
    c["schema_version"] = 10 ** 1000
    assert any("schema_version" in e for e in S.check_contract(c))  # not OverflowError
    issues = []
    req = S.from_contract(c, issues)
    assert any("kept as-is" in w for w in issues)
    assert S.to_contract(req)["schema_version"] == 10 ** 1000


def test_sealed_contract_survives_version_canonicalization():
    # a sealed contract re-serialized with schema_version: 3.0 (JSON number
    # semantics) must keep a valid approval hash through load canonicalization
    req = S.build_example()
    S.seal(req)
    c = S.to_contract(req)
    c["schema_version"] = 3.0
    assert S.check_contract(c) == []
    assert S.hash_status(c) == "ok"        # hash is version-canonical
    issues = []
    req2 = S.from_contract(c, issues)
    assert any("canonicalized to 3" in w for w in issues)
    c2 = S.to_contract(req2)
    assert c2["schema_version"] == 3
    assert S.hash_status(c2) == "ok"       # approval NOT invalidated
    assert S.check_contract(c2) == []
