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


def test_samples_off_by_default():
    # default (no env) = general builder: no sample kind, no biobank project type
    assert "sample" not in S.KINDS
    assert "biobank" not in S.PROJECT_TYPES


def test_samples_enabled_via_flag():
    # COHORT_ENABLE_SAMPLES=1 turns on the SHARE variant (checked in a clean subprocess)
    import os
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = ("import requirement_schema as S;"
            "assert 'sample' in S.KINDS;"
            "assert 'biobank' in S.PROJECT_TYPES;"
            "assert S.validate(S.build_example()) == [];"
            "print('ok')")
    r = subprocess.run([sys.executable, "-c", code], cwd=root,
                       env={**os.environ, "COHORT_ENABLE_SAMPLES": "1"},
                       capture_output=True, text=True)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr


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
    # content identical except the renamed group
    gc, cc = S.to_contract({"project": "x", "project_type": "biobank", "cohorts": [g]}), \
        S.to_contract({"project": "x", "project_type": "biobank", "cohorts": [clone]})
    assert clone["name"] == g["name"] + " (copy)"
    gc["cohorts"][0]["name"] = cc["cohorts"][0]["name"]
    assert gc == cc
