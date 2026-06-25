"""Throwaway Streamlit page to prove the autonomous screenshot loop."""
import streamlit as st

st.set_page_config(page_title="SHARE Requirement Builder", layout="wide")

with st.sidebar:
    st.title("SHARE Requirement Builder")
    st.subheader("Project")
    st.text_input("Title", "Lipidomics of Diabetic Retinopathy")
    st.radio("Type", ["biobank", "recruitment"], horizontal=True)
    st.text_input("Target N", "15 per group (90 total)")
    st.text_input("Ticket", "SHARE-2213")
    st.divider()
    st.subheader("Groups")
    st.radio("group", ["Group 3 — severe DR", "Control — no DR"], label_visibility="collapsed")
    st.button("➕ Add group")
    st.button("🗑 Remove this group")
    st.divider()
    st.subheader("YAML preview")
    st.code("project: Lipidomics…\nproject_type: biobank\ncohorts:\n  - name: Group 3…", language="yaml")
    st.download_button("⬇ Download YAML", "stub", "requirement.yaml")

st.text_input("Group name", "Group 3 — T2DM severe preproliferative DR")
st.caption("ⓘ This group = one complete RDMP build.")

with st.container(border=True):
    st.markdown("**INCLUSION (base population)**")
    st.radio("Container op", ["AND / INTERSECT", "OR / UNION"], horizontal=True)
    st.write("▸ [demographic] Adults 18–80, Scotland")
    st.write("▾ (OR) Type 2 diabetes (any source)")
    st.write("    ▸ [codes] SMR01 · ICD E11")
    st.write("    ▸ [codes] GP · READ C10E., C1087")
    st.write("▸ [sample] sample before first DR dx")
    c1, c2 = st.columns(2)
    c1.button("➕ Add condition")
    c2.button("➕ Add OR/AND group")

with st.container(border=True):
    st.markdown("**EXCLUSIONS (subtracted in order)**")
    st.write("1. [codes] SMR01 · ICD E78, E74, E75   ↑ ↓ ✎ ✕")
    st.write("2. [note] Prior intravitreal therapy   ↑ ↓ ✎ ✕")
    st.button("➕ Add exclusion")

st.success("validation: ✓ ready  (2 groups · this build OK)")
