# 🎫 Agentic Ticket Manager

**Agentic AI for Intelligent Service Ticket Management & SLA Compliance Monitoring**

A 3-agent AI pipeline that automates the full lifecycle of IT service tickets — from LLM-powered triage and team routing, to real-time SLA monitoring, to Slack and email breach alerts. No human triage needed.

---

## What it does

Manual ticket triage is slow and inconsistent. This system automates the entire lifecycle:

1. **Agent 1 (Categoriser)** — reads raw ticket text, classifies priority (Critical/High/Medium/Low), assigns the right team, scores urgency and impact, and explains its reasoning
2. **Agent 2 (SLA Monitor)** — evaluates each ticket against defined SLA windows, calculates how much of the time budget is used, and decides what action to take (warn / escalate / escalate to director)
3. **Agent 3 (Notifier)** — writes natural-language Slack alerts and emails for SLA breaches, using GPT-4o to keep messages clear and actionable rather than robotic

---

## Demo

```bash
streamlit run ui/app.py
```

Submit a ticket description and get:
- Priority classification with reasoning
- Team assignment from routing rules
- Urgency + impact scores
- Live SLA status with progress bars
- Auto-generated Slack alert (mock mode by default)

Or load 8 sample tickets and run the full batch pipeline.

---

## Architecture

```
Raw ticket text (user input / Jira / API)
         │
         ▼
┌──────────────────────────────────┐
│  Agent 1: Categoriser            │
│  ───────────────────────────── │
│  GPT-4o, temperature=0           │
│  Output: priority, team,         │
│  urgency/impact scores, summary  │
└───────────────┬──────────────────┘
                │
                ▼
┌──────────────────────────────────┐
│  Agent 2: SLA Monitor            │
│  ────────────────────────────── │
│  GPT-4o + SLA policy rules       │
│  Output: sla_status, action,     │
│  percent of window used          │
└───────────────┬──────────────────┘
                │ (if action needed)
                ▼
┌──────────────────────────────────┐
│  Agent 3: Notifier               │
│  ────────────────────────────── │
│  GPT-4o writes the alert message │
│  Sends to: Slack / Email / Mock  │
└──────────────────────────────────┘
```

---

## Stack

| Layer | Technology |
|-------|-----------|
| LLM | OpenAI GPT-4o |
| Agent framework | LangChain |
| Output validation | Pydantic v2 |
| UI | Streamlit |
| Alerts | Slack Webhooks + SMTP email |
| Tests | pytest + unittest.mock |

---

## Improvements over original

This project extends the [original capstone](https://github.com/mounishallu05/Agentic-AI-for-Intelligent-Service-Ticket-Management-and-SLA-Compliance-Monitoring) with:

- **Three independent agents** (original had one monolithic script per function) — easier to test, extend, and deploy separately
- **Pydantic v2 validation** on all agent outputs — no silent type errors downstream
- **Slack webhook alerts** replacing SMTP-only — more relevant to modern teams
- **LLM-written alert messages** — alerts read like a human wrote them, not a script
- **Mock mode throughout** — the full pipeline demos end-to-end with no external services
- **Streamlit UI** with single-ticket and batch modes
- **Full unit test suite** — all agents tested with mocked LLM calls

---

## Setup

```bash
# 1. Clone and install
git clone https://github.com/abhistac/agentic-ticket-manager.git
cd agentic-ticket-manager
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Add OPENAI_API_KEY to .env (everything else is optional for demo)

# 3. Run demo UI
streamlit run ui/app.py

# 4. Run tests (no API key needed)
pytest tests/ -v
```

**Optional — live Jira and Slack:**
```bash
# Add to .env:
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=you@email.com
JIRA_API_TOKEN=your-token
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

---

## SLA Policies

| Priority | Response target | Resolution target |
|----------|----------------|-------------------|
| Critical | 15 minutes | 4 hours |
| High | 1 hour | 8 hours |
| Medium | 4 hours | 24 hours |
| Low | 8 hours | 3 days |

---

## Author

**Abhista Atchutuni** — AI & Data Engineer  
[linkedin.com/in/abhistac](https://linkedin.com/in/abhistac) · [abhistaca@gmail.com](mailto:abhistaca@gmail.com)
