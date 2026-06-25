"""Playwright interaction tests: drive the real Streamlit app in a browser.

Proves the flows screenshots can't: the form serializes through the real
download button, add-group works, the leaf dialog adds a condition, reorder
swaps exclusion order, and validation reacts to a blank requirement.
"""
import re

import yaml

import requirement_schema as S
from conftest import settle


def download_yaml(page):
    with page.expect_download() as di:
        page.get_by_role("button", name="Download YAML").click()
    return yaml.safe_load(open(di.value.path()))


def test_app_loads_example(page):
    assert page.get_by_text("INCLUSION — base population").is_visible()
    # both example groups present in the sidebar selector
    assert page.get_by_role("radio", name="Control", exact=False).count() >= 1


def test_default_download_matches_contract(page):
    got = download_yaml(page)
    assert got == S.to_contract(S.build_example())


def test_add_group(page):
    # the example has no plain "Group 3" (it's "Group 3 — …"); adding makes one
    assert page.get_by_role("radio", name="Group 3", exact=True).count() == 0
    page.get_by_role("button", name="Add group").click()
    settle(page)
    assert page.get_by_role("radio", name="Group 3", exact=True).count() == 1


def test_add_exclusion_via_dialog(page):
    # match "➕ Add exclusion" but NOT "➕ Add exclusion group"
    page.get_by_role("button", name=re.compile(r"Add exclusion$")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Label").fill("Test exclusion")
    dlg.get_by_role("textbox", name="Source / catalogue").fill("TEST_CAT")
    dlg.get_by_role("textbox", name="ICD-10").fill("Z99")
    page.keyboard.press("Tab")
    settle(page)
    dlg.get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    excls = got["cohorts"][0]["exclusions"]
    assert any(e.get("source") == "TEST_CAT" and e.get("icd") == ["Z99"] for e in excls)


def test_reorder_exclusion(page):
    before = download_yaml(page)["cohorts"][0]["exclusions"]
    assert len(before) >= 2
    # click the first exclusion's down-arrow (first ↓ button on the page)
    page.get_by_role("button", name="↓").first.click()
    settle(page)
    after = download_yaml(page)["cohorts"][0]["exclusions"]
    assert [e.get("label") for e in after[:2]] == [
        before[1].get("label"), before[0].get("label")]


def test_blank_requirement_shows_validation(page):
    page.get_by_role("button", name="New (blank requirement)").click()
    settle(page)
    assert page.get_by_text("Not ready").is_visible()
    got = download_yaml(page)
    assert got["project"] == ""
