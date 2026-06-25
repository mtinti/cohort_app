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


def test_validate_sample_only_for_biobank():
    req = S.new_requirement()
    req["project"] = "x"
    req["project_type"] = "recruitment"
    req["cohorts"][0]["inclusion"]["members"].append(
        S.new_sample("s", codes=["2BBP."]))
    assert any("only valid for biobank" in e for e in S.validate(req))


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


def test_event_vocab_covers_all_event_types():
    assert set(S.EVENT_VOCAB) == set(S.EVENT_TYPES)
