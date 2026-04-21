"""
Notifier — Agent 3

Takes SLA evaluations that need action and sends alerts via:
  - Slack (webhook) — primary channel for team alerts
  - Email (SMTP) — for formal escalations
  - Mock mode — prints formatted output without hitting any external service

The LLM writes the alert message in natural language.
The notifier just handles delivery.

Key upgrade over original SMTP-only approach: Slack webhooks are
far more common in modern engineering teams, and this adds an
LLM-written message so alerts don't sound like robot output.
"""

import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel

from agents.sla_monitor import SLAEvaluation
from core.prompts import SLACK_MESSAGE_PROMPT

load_dotenv()


class NotificationResult(BaseModel):
    """Record of what was sent and to where."""
    ticket_id: str
    action_taken: str
    channels_used: list[str]
    message_preview: str
    success: bool
    error: Optional[str] = None


class NotifierAgent:
    """
    Sends SLA breach alerts via Slack and/or email.

    Always runs in mock mode unless credentials are explicitly provided.
    Mock mode prints formatted output so the demo works end-to-end
    without any external service configuration.

    Example:
        notifier = NotifierAgent()
        results = notifier.notify_batch(sla_evaluations)
    """

    def __init__(self, model: str = "gpt-4o"):
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.3,  # Some variation in message phrasing is fine
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        self.slack_webhook = os.getenv("SLACK_WEBHOOK_URL", "")
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.alert_recipients = [
            r.strip() for r in os.getenv("ALERT_RECIPIENTS", "").split(",") if r.strip()
        ]

    @property
    def slack_enabled(self) -> bool:
        return bool(self.slack_webhook)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.alert_recipients)

    def _generate_alert_message(self, evaluation: SLAEvaluation) -> str:
        """Use LLM to write a natural, clear Slack alert."""
        prompt = SLACK_MESSAGE_PROMPT.format(
            ticket_json=evaluation.model_dump_json(indent=2),
            sla_json=json.dumps({
                "status": evaluation.sla_status,
                "time_elapsed_minutes": evaluation.time_elapsed_minutes,
                "percent_resolution_used": evaluation.percent_resolution_used,
                "action_required": evaluation.action_required,
            }, indent=2),
        )
        messages = [HumanMessage(content=prompt)]
        response = self.llm.invoke(messages)
        return response.content.strip()

    def _send_slack(self, message: str) -> bool:
        """POST alert to Slack webhook."""
        try:
            response = requests.post(
                self.slack_webhook,
                json={"text": message},
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"  Slack send failed: {e}")
            return False

    def _send_email(self, subject: str, body: str) -> bool:
        """Send alert via SMTP."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_user
            msg["To"] = ", ".join(self.alert_recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.smtp_user, self.alert_recipients, msg.as_string())
            return True
        except Exception as e:
            print(f"  Email send failed: {e}")
            return False

    def notify(self, evaluation: SLAEvaluation) -> NotificationResult:
        """
        Send alert for a single SLA evaluation that requires action.

        Args:
            evaluation: SLAEvaluation where needs_alert is True

        Returns:
            NotificationResult recording what was sent
        """
        if not evaluation.needs_alert:
            return NotificationResult(
                ticket_id=evaluation.ticket_id,
                action_taken="none",
                channels_used=[],
                message_preview="No action required.",
                success=True,
            )

        # Generate the alert message via LLM
        if evaluation.alert_message:
            message = evaluation.alert_message
        else:
            message = self._generate_alert_message(evaluation)

        subject = (
            f"[{evaluation.sla_status.upper()}] SLA Alert: "
            f"{evaluation.ticket_id} ({evaluation.priority})"
        )

        channels_used = []
        success = True

        # Slack
        if self.slack_enabled:
            slack_ok = self._send_slack(f"*{subject}*\n{message}")
            if slack_ok:
                channels_used.append("slack")
            else:
                success = False
        else:
            # Mock mode — print formatted output
            channels_used.append("mock_slack")
            print(f"\n  {'='*60}")
            print(f"  [MOCK SLACK ALERT]")
            print(f"  {subject}")
            print(f"  {message}")
            print(f"  {'='*60}\n")

        # Email (escalations only)
        if self.email_enabled and evaluation.action_required in [
            "escalate_manager", "escalate_director"
        ]:
            email_ok = self._send_email(subject, message)
            if email_ok:
                channels_used.append("email")
            else:
                success = False
        elif evaluation.action_required in ["escalate_manager", "escalate_director"]:
            channels_used.append("mock_email")

        return NotificationResult(
            ticket_id=evaluation.ticket_id,
            action_taken=evaluation.action_required,
            channels_used=channels_used,
            message_preview=message[:200] + ("..." if len(message) > 200 else ""),
            success=success,
        )

    def notify_batch(
        self,
        evaluations: list[SLAEvaluation],
        verbose: bool = False,
    ) -> list[NotificationResult]:
        """
        Send alerts for all evaluations that need action.

        Args:
            evaluations: List of SLAEvaluation objects
            verbose: Print progress

        Returns:
            List of NotificationResult for every evaluation that needed action
        """
        results = []
        alerts_needed = [e for e in evaluations if e.needs_alert]

        if not alerts_needed:
            if verbose:
                print("  No SLA alerts needed.")
            return []

        for i, evaluation in enumerate(alerts_needed):
            if verbose:
                print(f"  Notifying {i+1}/{len(alerts_needed)}: {evaluation.ticket_id}...")
            result = self.notify(evaluation)
            results.append(result)

        return results
