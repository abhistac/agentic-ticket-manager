"""
Unit tests for Agentic Ticket Manager.
All LLM calls are mocked — tests run without an API key.

Run with: pytest tests/ -v
"""

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from agents.categoriser import CategorisingAgent, CategorisedTicket
from agents.sla_monitor import SLAMonitorAgent, SLAEvaluation
from agents.notifier import NotifierAgent, NotificationResult


# ── Fixtures ───────────────────────────────────────────────────────────────────

MOCK_CATEGORISE_RESPONSE = json.dumps({
    "priority": "Critical",
    "category": "application",
    "assigned_team": "Application Engineering",
    "urgency_score": 10,
    "impact_score": 9,
    "one_line_summary": "Production API returning 500 for all users",
    "reasoning": "100% of users affected with active revenue loss makes this Critical.",
})

MOCK_MEDIUM_RESPONSE = json.dumps({
    "priority": "Medium",
    "category": "network",
    "assigned_team": "Infrastructure",
    "urgency_score": 4,
    "impact_score": 3,
    "one_line_summary": "User unable to connect to VPN from home",
    "reasoning": "Single user affected, workaround possible, non-urgent timeline.",
})

MOCK_SLA_BREACHED_RESPONSE = json.dumps({
    "sla_status": "breached",
    "time_elapsed_minutes": 320,
    "response_sla_minutes": 15,
    "resolution_sla_minutes": 240,
    "percent_response_used": 100.0,
    "percent_resolution_used": 133.3,
    "action_required": "escalate_director",
    "alert_message": "TKT-001 has breached its 4-hour SLA. Immediate escalation required.",
    "breach_risk": "breached",
})

MOCK_SLA_WITHIN_RESPONSE = json.dumps({
    "sla_status": "within_sla",
    "time_elapsed_minutes": 5,
    "response_sla_minutes": 480,
    "resolution_sla_minutes": 4320,
    "percent_response_used": 1.0,
    "percent_resolution_used": 0.1,
    "action_required": "none",
    "alert_message": None,
    "breach_risk": "low",
})

MOCK_SLACK_MESSAGE = "TKT-001 has breached its SLA. Please escalate to the director immediately."


def make_mock_ticket(ticket_id: str = "TKT-001") -> CategorisedTicket:
    """Helper: build a CategorisedTicket without LLM calls."""
    return CategorisedTicket(
        ticket_id=ticket_id,
        raw_text="Production API is down for all users.",
        priority="Critical",
        category="application",
        assigned_team="Application Engineering",
        urgency_score=10,
        impact_score=9,
        one_line_summary="Production API returning 500 for all users",
        reasoning="Critical impact.",
    )


def make_mock_evaluation(
    ticket_id: str = "TKT-001",
    sla_status: str = "breached",
    action: str = "escalate_director",
) -> SLAEvaluation:
    """Helper: build an SLAEvaluation without LLM calls."""
    return SLAEvaluation(
        ticket_id=ticket_id,
        priority="Critical",
        assigned_team="Application Engineering",
        assignee="ops@company.com",
        sla_status=sla_status,
        time_elapsed_minutes=320,
        response_sla_minutes=15,
        resolution_sla_minutes=240,
        percent_response_used=100.0,
        percent_resolution_used=133.3,
        action_required=action,
        alert_message="SLA breached. Escalate now.",
        breach_risk="breached",
    )


# ── CategorisingAgent tests ────────────────────────────────────────────────────

class TestCategorisingAgent:

    @patch("agents.categoriser.ChatOpenAI")
    def test_categorise_critical_ticket(self, mock_llm_class):
        """Agent classifies a production outage as Critical."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_CATEGORISE_RESPONSE)
        mock_llm_class.return_value = mock_llm

        agent = CategorisingAgent()
        result = agent.categorise("TKT-001", "Production API is down for all users.")

        assert result.priority == "Critical"
        assert result.category == "application"
        assert result.urgency_score == 10
        assert result.ticket_id == "TKT-001"

    @patch("agents.categoriser.ChatOpenAI")
    def test_categorise_medium_ticket(self, mock_llm_class):
        """Agent classifies a VPN issue as Medium."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_MEDIUM_RESPONSE)
        mock_llm_class.return_value = mock_llm

        agent = CategorisingAgent()
        result = agent.categorise("TKT-002", "Can't connect to VPN from home.")

        assert result.priority == "Medium"
        assert result.category == "network"
        assert result.impact_score < 5

    @patch("agents.categoriser.ChatOpenAI")
    def test_risk_score_calculation(self, mock_llm_class):
        """Risk score is correct average of urgency and impact."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_CATEGORISE_RESPONSE)
        mock_llm_class.return_value = mock_llm

        agent = CategorisingAgent()
        result = agent.categorise("TKT-001", "Production down.")

        # urgency=10, impact=9 → risk=(10+9)/2=9.5
        assert result.risk_score == 9.5

    @patch("agents.categoriser.ChatOpenAI")
    def test_batch_skips_failures(self, mock_llm_class):
        """Batch categorisation continues if one ticket fails."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = [
            Exception("API error"),
            MagicMock(content=MOCK_MEDIUM_RESPONSE),
        ]
        mock_llm_class.return_value = mock_llm

        agent = CategorisingAgent()
        results = agent.categorise_batch([
            {"id": "TKT-001", "text": "bad ticket"},
            {"id": "TKT-002", "text": "good ticket"},
        ])

        # One failed, one succeeded
        assert len(results) == 1
        assert results[0].ticket_id == "TKT-002"

    def test_invalid_priority_raises(self):
        """Pydantic rejects invalid priority values."""
        with pytest.raises(ValidationError):
            CategorisedTicket(
                ticket_id="TKT-001",
                raw_text="test",
                priority="SuperCritical",  # Invalid
                category="application",
                assigned_team="Engineering",
                urgency_score=5,
                impact_score=5,
                one_line_summary="test",
                reasoning="test",
            )

    def test_score_out_of_range_raises(self):
        """Pydantic rejects scores outside 1-10."""
        with pytest.raises(ValidationError):
            CategorisedTicket(
                ticket_id="TKT-001",
                raw_text="test",
                priority="High",
                category="application",
                assigned_team="Engineering",
                urgency_score=11,  # Invalid
                impact_score=5,
                one_line_summary="test",
                reasoning="test",
            )


# ── SLAMonitorAgent tests ──────────────────────────────────────────────────────

class TestSLAMonitorAgent:

    @patch("agents.sla_monitor.ChatOpenAI")
    def test_evaluate_breached(self, mock_llm_class):
        """Agent correctly identifies a breached SLA."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_SLA_BREACHED_RESPONSE)
        mock_llm_class.return_value = mock_llm

        ticket = make_mock_ticket()
        agent = SLAMonitorAgent()
        result = agent.evaluate(
            ticket=ticket,
            created_at=datetime.now(timezone.utc) - timedelta(hours=6),
            assignee="ops@company.com",
        )

        assert result.sla_status == "breached"
        assert result.action_required == "escalate_director"
        assert result.needs_alert is True

    @patch("agents.sla_monitor.ChatOpenAI")
    def test_evaluate_within_sla(self, mock_llm_class):
        """Agent correctly identifies a ticket within SLA."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_SLA_WITHIN_RESPONSE)
        mock_llm_class.return_value = mock_llm

        ticket = make_mock_ticket()
        agent = SLAMonitorAgent()
        result = agent.evaluate(
            ticket=ticket,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            assignee="ops@company.com",
        )

        assert result.sla_status == "within_sla"
        assert result.action_required == "none"
        assert result.needs_alert is False

    @patch("agents.sla_monitor.ChatOpenAI")
    def test_needs_alert_property(self, mock_llm_class):
        """needs_alert is True only when action is required."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_SLA_BREACHED_RESPONSE)
        mock_llm_class.return_value = mock_llm

        ticket = make_mock_ticket()
        agent = SLAMonitorAgent()
        result = agent.evaluate(
            ticket=ticket,
            created_at=datetime.now(timezone.utc) - timedelta(hours=6),
            assignee="ops@company.com",
        )

        assert result.needs_alert is True

    def test_status_emoji_property(self):
        """status_emoji returns the correct icon."""
        eval_within = make_mock_evaluation(sla_status="within_sla", action="none")
        # Override sla_status for this test
        eval_within = SLAEvaluation(**{**eval_within.model_dump(), "sla_status": "within_sla", "action_required": "none"})
        assert eval_within.status_emoji == "🟢"

        eval_breach = make_mock_evaluation(sla_status="breached")
        assert eval_breach.status_emoji == "🔴"


# ── NotifierAgent tests ────────────────────────────────────────────────────────

class TestNotifierAgent:

    @patch("agents.notifier.ChatOpenAI")
    def test_no_alert_for_compliant(self, mock_llm_class):
        """Notifier skips tickets with no action required."""
        mock_llm_class.return_value = MagicMock()

        evaluation = make_mock_evaluation(sla_status="within_sla", action="none")
        # Override to no action
        evaluation = SLAEvaluation(**{**evaluation.model_dump(), "action_required": "none", "sla_status": "within_sla"})

        agent = NotifierAgent()
        result = agent.notify(evaluation)

        assert result.action_taken == "none"
        assert result.channels_used == []

    @patch("agents.notifier.ChatOpenAI")
    @patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "", "SMTP_HOST": ""}, clear=False)
    def test_mock_mode_used_without_credentials(self, mock_llm_class):
        """Without Slack/email credentials, mock mode is used."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_SLACK_MESSAGE)
        mock_llm_class.return_value = mock_llm

        evaluation = make_mock_evaluation()
        agent = NotifierAgent()

        # Credentials cleared → mock mode
        assert not agent.slack_enabled
        result = agent.notify(evaluation)

        assert "mock_slack" in result.channels_used
        assert result.success is True

    @patch("agents.notifier.ChatOpenAI")
    def test_batch_only_notifies_alerts(self, mock_llm_class):
        """notify_batch only processes tickets that need action."""
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content=MOCK_SLACK_MESSAGE)
        mock_llm_class.return_value = mock_llm

        breach = make_mock_evaluation("TKT-001", "breached", "escalate_director")
        ok = make_mock_evaluation("TKT-002", "within_sla", "none")
        ok = SLAEvaluation(**{**ok.model_dump(), "sla_status": "within_sla", "action_required": "none"})

        agent = NotifierAgent()
        results = agent.notify_batch([breach, ok])

        # Only the breached one triggers a notification
        assert len(results) == 1
        assert results[0].ticket_id == "TKT-001"
