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
    assert S.KINDS == ["demographic", "codes", "sample", "note"]
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
            "assert S.KINDS == ['demographic', 'codes', 'sample', 'note'];"
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
    contract = {"project": "x", "project_type": "recruitment", "schema_version": 1,
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
            "schema_version": 1,
            "cohorts": [{"id": "g1", "name": "G", "exclusions": [], "inclusion": {
                "id": "c1", "op": "AND", "members": [
                    {"id": "l1", "kind": "codes", "label": "c",
                     "source": "hospital", "icd": ["A00"]}]}}]}


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
