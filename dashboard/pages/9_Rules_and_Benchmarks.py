from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import streamlit as st

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = DASHBOARD_DIR.parent
for path in (PROJECT_ROOT, DASHBOARD_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.schemas.category_rule import CategoryRuleCreate, CategoryRuleUpdate
from app.services.benchmarks import list_benchmarks, update_benchmark
from app.services.category_rules import (
    create_category_rule,
    delete_category_rule,
    list_category_rules,
    reapply_category_rules,
    update_category_rule,
)
from common import benchmark_profile_options, category_options, initialize_page, render_sidebar_status, session_scope


initialize_page("Rules and Benchmarks")
render_sidebar_status()

st.title("Rules and Benchmarks")
st.caption("Edit local categorization rules and Hyderabad benchmark ranges without sending any data outside this machine.")

categories = category_options()

st.subheader("Category rules")
with session_scope() as session:
    rules = list_category_rules(session)

if rules:
    rules_df = pd.DataFrame(
        [
            {
                "id": rule.id,
                "name": rule.name,
                "pattern": rule.pattern,
                "field": rule.field_name,
                "category": rule.target_category,
                "subcategory": rule.target_subcategory or "",
                "priority": rule.priority,
                "regex": rule.is_regex,
                "case_sensitive": rule.case_sensitive,
                "active": rule.is_active,
            }
            for rule in rules
        ]
    )
    st.dataframe(rules_df, use_container_width=True, hide_index=True)
else:
    st.info("No category rules found.")

rule_action_columns = st.columns(2)
if rule_action_columns[0].button("Reapply all rules to low-confidence transactions", use_container_width=True):
    with session_scope() as session:
        updated_count = reapply_category_rules(session, only_low_confidence=True)
    st.success(f"Updated {updated_count} low-confidence transactions.")
    st.rerun()

if rule_action_columns[1].button("Reapply all rules to all transactions", use_container_width=True):
    with session_scope() as session:
        updated_count = reapply_category_rules(session)
    st.success(f"Updated {updated_count} transactions.")
    st.rerun()

with st.expander("Add category rule", expanded=False):
    with st.form("add-category-rule"):
        new_name = st.text_input("Rule name")
        new_pattern = st.text_input("Match pattern", placeholder="swiggy|zomato|uber")
        new_category = st.selectbox("Target category", categories, key="new_rule_category")
        new_subcategory = st.text_input("Target subcategory")
        new_priority = st.number_input("Priority", min_value=0, max_value=1000, value=80)
        new_is_regex = st.checkbox("Treat pattern as regex", value=True)
        new_case_sensitive = st.checkbox("Case sensitive", value=False)
        new_active = st.checkbox("Active", value=True)
        add_submitted = st.form_submit_button("Create rule", use_container_width=True)

    if add_submitted:
        try:
            with session_scope() as session:
                create_category_rule(
                    session,
                    CategoryRuleCreate(
                        name=new_name,
                        pattern=new_pattern,
                        target_category=new_category,
                        target_subcategory=new_subcategory or None,
                        priority=int(new_priority),
                        is_regex=new_is_regex,
                        case_sensitive=new_case_sensitive,
                        is_active=new_active,
                    ),
                )
            st.success("Category rule created.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not create rule: {exc}")

if rules:
    st.subheader("Edit existing rule")
    rule_lookup = {f"{rule.id} | {rule.name} | {rule.target_category}": rule for rule in rules}
    selected_rule_key = st.selectbox("Select rule", list(rule_lookup.keys()))
    selected_rule = rule_lookup[selected_rule_key]

    edit_columns = st.columns(2)
    with edit_columns[0]:
        edited_name = st.text_input("Rule name", value=selected_rule.name)
        edited_pattern = st.text_area("Pattern", value=selected_rule.pattern, height=120)
        edited_category = st.selectbox(
            "Target category",
            categories,
            index=categories.index(selected_rule.target_category) if selected_rule.target_category in categories else 0,
            key="edit_rule_category",
        )
        edited_subcategory = st.text_input("Target subcategory", value=selected_rule.target_subcategory or "")
    with edit_columns[1]:
        edited_priority = st.number_input("Priority", min_value=0, max_value=1000, value=selected_rule.priority)
        edited_is_regex = st.checkbox("Regex", value=selected_rule.is_regex)
        edited_case_sensitive = st.checkbox("Case sensitive", value=selected_rule.case_sensitive)
        edited_active = st.checkbox("Active", value=selected_rule.is_active)

    save_columns = st.columns(2)
    if save_columns[0].button("Save rule changes", use_container_width=True, type="primary"):
        try:
            with session_scope() as session:
                update_category_rule(
                    session,
                    selected_rule.id,
                    CategoryRuleUpdate(
                        name=edited_name,
                        pattern=edited_pattern,
                        target_category=edited_category,
                        target_subcategory=edited_subcategory or None,
                        priority=int(edited_priority),
                        is_regex=edited_is_regex,
                        case_sensitive=edited_case_sensitive,
                        is_active=edited_active,
                    ),
                )
            st.success("Rule updated.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not update rule: {exc}")

    if save_columns[1].button("Delete rule", use_container_width=True):
        try:
            with session_scope() as session:
                delete_category_rule(session, selected_rule.id)
            st.success("Rule deleted.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not delete rule: {exc}")

st.subheader("Hyderabad benchmark ranges")
profiles = benchmark_profile_options()
selected_profile = st.selectbox("Benchmark profile", profiles, index=profiles.index("Comfortable living") if "Comfortable living" in profiles else 0)

with session_scope() as session:
    benchmarks = list_benchmarks(session, city="Hyderabad", profile=selected_profile)

if not benchmarks:
    st.info("No benchmarks available for this profile.")
    st.stop()

benchmark_df = pd.DataFrame(
    [
        {
            "benchmark_id": benchmark.id,
            "city": benchmark.city,
            "profile": benchmark.profile,
            "category": benchmark.category,
            "min_amount": float(benchmark.min_amount),
            "max_amount": float(benchmark.max_amount),
            "is_active": benchmark.is_active,
        }
        for benchmark in benchmarks
    ]
).set_index("benchmark_id")

edited_benchmark_df = st.data_editor(
    benchmark_df,
    use_container_width=True,
    hide_index=False,
    disabled=["city", "profile", "category"],
    column_config={
        "min_amount": st.column_config.NumberColumn("Min amount", format="%.2f"),
        "max_amount": st.column_config.NumberColumn("Max amount", format="%.2f"),
        "is_active": st.column_config.CheckboxColumn("Active"),
    },
)

if st.button("Save benchmark changes", use_container_width=True, type="primary"):
    changed_count = 0
    try:
        with session_scope() as session:
            for benchmark_id, edited_row in edited_benchmark_df.iterrows():
                original_row = benchmark_df.loc[benchmark_id]
                if (
                    float(edited_row["min_amount"]) != float(original_row["min_amount"])
                    or float(edited_row["max_amount"]) != float(original_row["max_amount"])
                    or bool(edited_row["is_active"]) != bool(original_row["is_active"])
                ):
                    update_benchmark(
                        session=session,
                        benchmark_id=int(benchmark_id),
                        min_amount=float(edited_row["min_amount"]),
                        max_amount=float(edited_row["max_amount"]),
                        is_active=bool(edited_row["is_active"]),
                    )
                    changed_count += 1
        if changed_count == 0:
            st.info("No benchmark changes detected.")
        else:
            st.success(f"Updated {changed_count} benchmark rows.")
            st.rerun()
    except Exception as exc:
        st.error(f"Could not update benchmarks: {exc}")
