"""
SLA Monitor — Agent 2

Takes a categorised ticket + its age and evaluates SLA compliance.
Decides whether to:
  - Do nothing (within SLA)
  - Warn the assignee (at risk)
  - Escalate to manager or director (breached)

Key upgrade over original: LLM reasons about SLA status rather than
a simple time comparison. It considers ticket context, partial
responses, and business hours to give smarter recommendations.
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, field_validator

from agents.categoriser import CategorisedTicket
from core.sla_rules import get_sla_context, get_sla_limits
from core.prompts import SLA_MONITOR_SYSTEM_PROMPT, SLA_MONITOR_USER_PROMPT

load_dotenv()

VALID_SLA_STATUSES = {"within_sla", "at_risk", "breached"}
VALID_ACTIONS = {"none", "warn_assignee", "escalate_manager", "escalate_director"}
VALID_BREACH_RISKS = {"low", "medium", "high", "breached"}


class SLAEvaluation(BaseModel):
    """Structured output from the SLA monitor."""
    ticket_id: str
    priority: str
    assigned_team: str
    assignee: str
    sla_status: str
    time_elapsed_minutes: int
    response_sla_minutes: int
    resolution_sla_minutes: int
    percent_response_used: float
    percent_resolution_used: float
    action_required: str
    alert_message: Optional[str] = None
    breach_risk: str

    @field_validator("sla_status")
    @classmethod
    def sla_status_valid(cls, v):
        if v not in VALID_SLA_STATUSES:
            raise ValueError(f"sla_status must be one of {VALID_SLA_STATUSES}")
        return v

    @field_validator("action_required")
    @classmethod
    def action_valid(cls, v):
        if v not in VALID_ACTIONS:
            raise ValueError(f"action_required must be one of {VALID_ACTIONS}")
        return v

    @field_validator("breach_risk")
    @classmethod
    def breach_risk_valid(cls, v):
        if v not in VALID_BREACH_RISKS:
            raise ValueError(f"breach_risk must be one of {VALID_BREACH_RISKS}")
        return v

    @property
    def needs_alert(self) -> bool:
        return self.action_required != "none"

    @property
    def status_emoji(self) -> str:
        return {
            "within_sla": "🟢",
            "at_risk": "🟡",
            "breached": "🔴",
        }.get(self.sla_status, "⚪")


class SLAMonitorAgent:
    """
    Evaluates SLA compliance for categorised tickets.

    Example:
        agent = SLAMonitorAgent()
        eval = agent.evaluate(
            ticket=categorised_ticket,
            created_at=datetime(2024, 1, 15, 9, 0, tzinfo=timezone.utc),
            assignee="john.smith@company.com",
            status="Open",
        )
        if eval.needs_alert:
            print(eval.alert_message)
    """

    def __init__(self, model: str = "gpt-4o"):
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.1,
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        self.sla_context = get_sla_context()

    def _call_llm(self, system: str, human: str) -> str:
        messages = [SystemMessage(content=system), HumanMessage(content=human)]
        response = self.llm.invoke(messages)
        return response.content.strip()

    def _parse_json(self, raw: str) -> dict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:-1])
        return json.loads(cleaned)

    def evaluate(
        self,
        ticket: CategorisedTicket,
        created_at: datetime,
        assignee: str,
        status: str = "Open",
    ) -> SLAEvaluation:
        """
        Evaluate SLA status for a single ticket.

        Args:
            ticket: CategorisedTicket from Agent 1
            created_at: When the ticket was created (timezone-aware datetime)
            assignee: Who the ticket is assigned to
            status: Current ticket status (Open, In Progress, Pending, etc.)

        Returns:
            SLAEvaluation with status, action, and alert message
        """
        now = datetime.now(timezone.utc)
        # Ensure created_at is timezone-aware
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        user_prompt = SLA_MONITOR_USER_PROMPT.format(
            ticket_json=ticket.model_dump_json(indent=2),
            sla_context=self.sla_context,
            current_time=now.strftime("%Y-%m-%d %H:%M UTC"),
            created_at=created_at.strftime("%Y-%m-%d %H:%M UTC"),
            status=status,
            assignee=assignee,
        )
        raw = self._call_llm(SLA_MONITOR_SYSTEM_PROMPT, user_prompt)
        data = self._parse_json(raw)

        return SLAEvaluation(
            ticket_id=ticket.ticket_id,
            priority=ticket.priority,
            assigned_team=ticket.assigned_team,
            assignee=assignee,
            **data,
        )

    def evaluate_batch(
        self,
        tickets_with_meta: list[dict],
        verbose: bool = False,
    ) -> list[SLAEvaluation]:
        """
        Evaluate SLA for a batch of tickets.

        Args:
            tickets_with_meta: List of dicts with keys:
                'ticket' (CategorisedTicket), 'created_at', 'assignee', 'status'
            verbose: Print progress

        Returns:
            List of SLAEvaluation objects
        """
        results = []
        for i, item in enumerate(tickets_with_meta):
            if verbose:
                print(f"  Evaluating SLA {i+1}/{len(tickets_with_meta)}: {item['ticket'].ticket_id}...")
            try:
                result = self.evaluate(
                    ticket=item["ticket"],
                    created_at=item["created_at"],
                    assignee=item.get("assignee", "unassigned@company.com"),
                    status=item.get("status", "Open"),
                )
                results.append(result)
            except Exception as e:
                print(f"  Warning: SLA eval failed for {item['ticket'].ticket_id}: {e}")
        return results
