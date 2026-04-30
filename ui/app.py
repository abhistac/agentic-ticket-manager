"""
Agentic Ticket Manager — Streamlit Demo UI

Submit a ticket, get instant classification, SLA evaluation, and alerts.
Or load sample tickets to see batch processing in action.

Run with:
    streamlit run ui/app.py
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

# Load API key from Streamlit Cloud secrets if running in cloud
# Falls back to .env for local development
import os
if hasattr(st, "secrets") and "OPENAI_API_KEY" in st.secrets:
    os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]

from agents.compliance_agent import ComplianceAgent, BatchResult
from agents.ticketing_agent import TicketingAgent

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Agentic Ticket Manager",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🎫 Ticket Manager")
    st.caption("Agentic AI for IT Service Desk")
    st.divider()

    st.subheader("Mode")
    mode = st.radio(
        "Input mode",
        ["Single ticket", "Batch (sample data)"],
        label_visibility="collapsed",
    )

    st.divider()
    st.subheader("About")
    st.markdown(
        """
        Built by **Abhista Atchutuni**

        A 3-agent pipeline that:
        - Categorises tickets by priority and team
        - Evaluates SLA compliance in real time
        - Sends Slack/email alerts on breaches

        [GitHub](https://github.com/abhistac) · [LinkedIn](https://linkedin.com/in/abhistac)
        """
    )

# ── Priority colors ────────────────────────────────────────────────────────────

PRIORITY_COLORS = {
    "Critical": "🔴",
    "High": "🟠",
    "Medium": "🟡",
    "Low": "🔵",
}

SLA_COLORS = {
    "within_sla": "🟢",
    "at_risk": "🟡",
    "breached": "🔴",
}

# ── Single ticket mode ─────────────────────────────────────────────────────────

def run_single_ticket():
    st.title("Submit a Ticket")
    st.caption("Describe your issue — the agent classifies it, assigns it, and checks SLA.")

    col1, col2 = st.columns([3, 1])
    with col1:
        ticket_text = st.text_area(
            "Ticket description",
            height=140,
            placeholder="e.g. Production API is returning 500 errors for all users. Started 10 minutes ago.",
        )
    with col2:
        ticket_id = st.text_input("Ticket ID", value="TKT-001")
        assignee = st.text_input("Assignee", value="ops.team@company.com")
        minutes_open = st.number_input(
            "Minutes since opened", min_value=0, max_value=10000, value=30
        )

    submit = st.button("Classify & Evaluate", type="primary")

    if submit:
        if not ticket_text.strip():
            st.warning("Please enter a ticket description.")
            return
        if not os.getenv("OPENAI_API_KEY"):
            st.error("OPENAI_API_KEY not set. Add it to your .env file.")
            return

        created_at = datetime.now(timezone.utc).replace(
            minute=max(0, datetime.now(timezone.utc).minute - minutes_open % 60)
        )

        with st.spinner("Agent 1: Classifying ticket..."):
            try:
                cat_agent = CategorisingAgent()
                ticket = cat_agent.categorise(ticket_id, ticket_text)
            except Exception as e:
                st.error(f"Classification failed: {e}")
                return

        with st.spinner("Agent 2: Evaluating SLA..."):
            try:
                sla_agent = SLAMonitorAgent()
                evaluation = sla_agent.evaluate(
                    ticket=ticket,
                    created_at=created_at,
                    assignee=assignee,
                    status="Open",
                )
            except Exception as e:
                st.error(f"SLA evaluation failed: {e}")
                return

        # ── Results ──
        st.divider()
        st.subheader("Classification")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Priority",
            f"{PRIORITY_COLORS.get(ticket.priority, '')} {ticket.priority}"
        )
        c2.metric("Team", ticket.assigned_team)
        c3.metric("Risk score", f"{ticket.risk_score}/10")
        c4.metric("Category", ticket.category.title())

        with st.expander("Full classification details"):
            st.markdown(f"**Summary:** {ticket.one_line_summary}")
            st.markdown(f"**Reasoning:** {ticket.reasoning}")
            col_u, col_i = st.columns(2)
            col_u.metric("Urgency", f"{ticket.urgency_score}/10")
            col_i.metric("Impact", f"{ticket.impact_score}/10")

        st.divider()
        st.subheader("SLA Status")

        s1, s2, s3 = st.columns(3)
        sla_icon = SLA_COLORS.get(evaluation.sla_status, "⚪")
        s1.metric("Status", f"{sla_icon} {evaluation.sla_status.replace('_', ' ').title()}")
        s2.metric("Time elapsed", f"{evaluation.time_elapsed_minutes} min")
        s3.metric("Resolution SLA", f"{evaluation.resolution_sla_minutes} min")

        col_r, col_res = st.columns(2)
        with col_r:
            pct_r = min(evaluation.percent_response_used, 100)
            st.markdown("**Response SLA used**")
            color = "normal" if pct_r < 75 else ("off" if pct_r < 100 else "inverse")
            st.progress(pct_r / 100, text=f"{pct_r:.0f}%")

        with col_res:
            pct_res = min(evaluation.percent_resolution_used, 100)
            st.markdown("**Resolution SLA used**")
            st.progress(pct_res / 100, text=f"{pct_res:.0f}%")

        if evaluation.needs_alert:
            st.divider()
            action_labels = {
                "warn_assignee": "⚠️ Warning sent to assignee",
                "escalate_manager": "🔺 Escalated to manager",
                "escalate_director": "🚨 Escalated to director",
            }
            st.warning(action_labels.get(evaluation.action_required, evaluation.action_required))
            if evaluation.alert_message:
                with st.expander("Alert message"):
                    st.markdown(evaluation.alert_message)
        else:
            st.success("✅ Within SLA — no action needed.")


# ── Batch mode ─────────────────────────────────────────────────────────────────

def run_batch():
    st.title("Batch Ticket Processing")
    st.caption("Processes all sample tickets through the full 3-agent pipeline.")

    sample_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "sample_tickets", "tickets.json"
    )

    with open(sample_path) as f:
        raw_tickets = json.load(f)

    st.info(f"Loaded {len(raw_tickets)} sample tickets. Click Run to process them all.")

    with st.expander("Preview sample tickets"):
        for t in raw_tickets:
            st.markdown(f"**{t['id']}** — {t['text'][:100]}...")

    run_btn = st.button("Run full pipeline", type="primary")

    if run_btn:
        if not os.getenv("OPENAI_API_KEY"):
            st.error("OPENAI_API_KEY not set. Add it to your .env file.")
            return

        tickets_input = [{"id": t["id"], "text": t["text"]} for t in raw_tickets]

        with st.spinner(f"Agent 1: Classifying {len(tickets_input)} tickets..."):
            cat_agent = CategorisingAgent()
            categorised = cat_agent.categorise_batch(tickets_input, verbose=False)

        # Build metadata for SLA evaluation
        tickets_with_meta = []
        for cat, raw in zip(categorised, raw_tickets):
            created_at = datetime.fromisoformat(
                raw["created_at"].replace("Z", "+00:00")
            )
            tickets_with_meta.append({
                "ticket": cat,
                "created_at": created_at,
                "assignee": raw.get("assignee", "unassigned@company.com"),
                "status": raw.get("status", "Open"),
            })

        with st.spinner("Agent 2: Evaluating SLA compliance..."):
            sla_agent = SLAMonitorAgent()
            evaluations = sla_agent.evaluate_batch(tickets_with_meta, verbose=False)

        with st.spinner("Agent 3: Sending alerts for breaches..."):
            notifier = NotifierAgent()
            notifications = notifier.notify_batch(evaluations, verbose=False)

        # ── Summary ──
        st.divider()
        st.subheader("Pipeline Summary")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Tickets processed", len(categorised))
        breached = sum(1 for e in evaluations if e.sla_status == "breached")
        at_risk = sum(1 for e in evaluations if e.sla_status == "at_risk")
        m2.metric("SLA breaches", breached)
        m3.metric("At risk", at_risk)
        m4.metric("Alerts sent", len(notifications))

        # ── Per-ticket results ──
        st.divider()
        st.subheader("Ticket Results")

        eval_by_id = {e.ticket_id: e for e in evaluations}

        for ticket in categorised:
            evaluation = eval_by_id.get(ticket.ticket_id)
            priority_icon = PRIORITY_COLORS.get(ticket.priority, "⚪")
            sla_icon = SLA_COLORS.get(evaluation.sla_status, "⚪") if evaluation else "⚪"

            label = f"{priority_icon} {ticket.ticket_id} — {ticket.one_line_summary}"
            expanded = ticket.priority in ["Critical", "High"] or (
                evaluation and evaluation.sla_status != "within_sla"
            )

            with st.expander(label, expanded=expanded):
                col_a, col_b, col_c = st.columns(3)
                col_a.markdown(f"**Priority:** {priority_icon} {ticket.priority}")
                col_a.markdown(f"**Team:** {ticket.assigned_team}")
                col_a.markdown(f"**Category:** {ticket.category.title()}")
                col_b.markdown(f"**Urgency:** {ticket.urgency_score}/10")
                col_b.markdown(f"**Impact:** {ticket.impact_score}/10")
                col_b.markdown(f"**Risk score:** {ticket.risk_score}/10")
                if evaluation:
                    col_c.markdown(f"**SLA status:** {sla_icon} {evaluation.sla_status.replace('_', ' ').title()}")
                    col_c.markdown(f"**Time elapsed:** {evaluation.time_elapsed_minutes} min")
                    col_c.markdown(f"**Action:** {evaluation.action_required}")

                st.markdown(f"**Reasoning:** {ticket.reasoning}")


# ── Router ─────────────────────────────────────────────────────────────────────

if mode == "Single ticket":
    run_single_ticket()
else:
    run_batch()
