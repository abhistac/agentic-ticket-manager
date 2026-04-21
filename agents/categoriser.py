"""
Ticket Categoriser — Agent 1

Reads raw ticket text and produces structured classification:
priority, category, team assignment, urgency/impact scores.

Key upgrade over the original: Pydantic validation means bad LLM
output is caught immediately, not silently propagated downstream.
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, field_validator

from core.sla_rules import get_sla_context, get_routing_context
from core.prompts import CATEGORISER_SYSTEM_PROMPT, CATEGORISER_USER_PROMPT

load_dotenv()

VALID_PRIORITIES = {"Critical", "High", "Medium", "Low"}
VALID_CATEGORIES = {"network", "security", "database", "application", "hardware", "authentication"}


class CategorisedTicket(BaseModel):
    """Structured output from the categoriser agent."""
    # Original fields
    ticket_id: str
    raw_text: str
    # LLM-generated fields
    priority: str
    category: str
    assigned_team: str
    urgency_score: int
    impact_score: int
    one_line_summary: str
    reasoning: str

    @field_validator("priority")
    @classmethod
    def priority_must_be_valid(cls, v):
        if v not in VALID_PRIORITIES:
            raise ValueError(f"priority must be one of {VALID_PRIORITIES}, got '{v}'")
        return v

    @field_validator("category")
    @classmethod
    def category_must_be_valid(cls, v):
        v_lower = v.lower()
        if v_lower not in VALID_CATEGORIES:
            raise ValueError(f"category must be one of {VALID_CATEGORIES}, got '{v}'")
        return v_lower

    @field_validator("urgency_score", "impact_score")
    @classmethod
    def score_must_be_in_range(cls, v):
        if not 1 <= v <= 10:
            raise ValueError(f"Score must be between 1 and 10, got {v}")
        return v

    @property
    def risk_score(self) -> float:
        """Composite risk = average of urgency and impact, scaled to 10."""
        return round((self.urgency_score + self.impact_score) / 2, 1)


class CategorisingAgent:
    """
    Categorises and routes incoming service tickets using GPT-4o.

    Example:
        agent = CategorisingAgent()
        ticket = agent.categorise("TKT-001", "Production API is returning 500 errors for all users")
        print(ticket.priority, ticket.assigned_team)
    """

    def __init__(self, model: str = "gpt-4o"):
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.0,  # Deterministic classification
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        self.sla_context = get_sla_context()
        self.routing_context = get_routing_context()

    def _call_llm(self, system: str, human: str) -> str:
        messages = [SystemMessage(content=system), HumanMessage(content=human)]
        response = self.llm.invoke(messages)
        return response.content.strip()

    def _parse_json(self, raw: str) -> dict:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:-1])
        return json.loads(cleaned)

    def categorise(self, ticket_id: str, ticket_text: str) -> CategorisedTicket:
        """
        Classify a single ticket.

        Args:
            ticket_id: Unique ticket identifier (e.g. 'TKT-001')
            ticket_text: Raw ticket description from the user

        Returns:
            CategorisedTicket with priority, team, scores, summary
        """
        user_prompt = CATEGORISER_USER_PROMPT.format(
            ticket_text=ticket_text,
            sla_context=self.sla_context,
            routing_context=self.routing_context,
        )
        raw = self._call_llm(CATEGORISER_SYSTEM_PROMPT, user_prompt)
        data = self._parse_json(raw)

        return CategorisedTicket(
            ticket_id=ticket_id,
            raw_text=ticket_text,
            **data,
        )

    def categorise_batch(
        self,
        tickets: list[dict],
        verbose: bool = False,
    ) -> list[CategorisedTicket]:
        """
        Classify a list of tickets.

        Args:
            tickets: List of dicts with 'id' and 'text' keys
            verbose: Print progress to stdout

        Returns:
            List of CategorisedTicket objects
        """
        results = []
        for i, ticket in enumerate(tickets):
            if verbose:
                print(f"  Categorising {i+1}/{len(tickets)}: {ticket['id']}...")
            try:
                result = self.categorise(ticket["id"], ticket["text"])
                results.append(result)
            except Exception as e:
                print(f"  Warning: failed to categorise {ticket['id']}: {e}")
        return results
