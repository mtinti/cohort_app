"""Interaction tests for the COHORT_ENABLE_SAMPLES=1 UI variant (own server).

The flag only widens what the UI OFFERS (sample kind, biobank project type);
these tests prove the widened form works end-to-end and still emits
gate-clean contracts.
"""
import re

import yaml

import requirement_schema as S
from conftest import settle


def download_yaml(page):
    with page.expect_download() as di:
        page.get_by_role("button", name="Download YAML").click()
    return yaml.safe_load(open(di.value.path()))


def test_flag_offers_biobank_and_sample(page_flag):
    page = page_flag
    assert page.get_by_role("radio", name="biobank").count() == 1   # project type
    # the example (flag on) already contains a sample condition, rendered fine
    assert page.get_by_text("[sample]").count() >= 1


def test_add_sample_condition_and_export(page_flag):
    page = page_flag
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.locator("[data-baseweb='select']").nth(0).click()           # Kind
    settle(page, 400)
    page.get_by_role("option", name="sample", exact=True).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Event codes (one per line)").fill("X9999")
    dlg.get_by_role("textbox",
                    name="Within N (blank = any time in that direction)").fill("3")
    page.keyboard.press("Tab")
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name="Save").click()
    settle(page)
    got = download_yaml(page)
    leaf = got["cohorts"][0]["inclusion"]["members"][-1]
    assert leaf["kind"] == "sample"
    assert leaf["sample_event"]["event"]["type"] == "gp_data"
    assert leaf["sample_event"]["event"]["codes"] == ["X9999"]
    assert leaf["sample_event"]["within"] == {"n": 3, "unit": "months"}
    assert S.check_contract(got) == []


def test_sample_event_code_warning(page_flag):
    page = page_flag
    page.get_by_role("button", name=re.compile(r"Add inclusion$")).click()
    settle(page)
    page.get_by_role("dialog").get_by_role("button", name=re.compile("Condition")).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.locator("[data-baseweb='select']").nth(0).click()
    settle(page, 400)
    page.get_by_role("option", name="sample", exact=True).click()
    settle(page)
    dlg = page.get_by_role("dialog")
    dlg.get_by_role("textbox", name="Event codes (one per line)").fill("A1")  # not 5 chars
    page.keyboard.press("Tab")
    settle(page)
    assert page.get_by_role("dialog").get_by_text(
        re.compile("invalid READ: A1")).is_visible()
