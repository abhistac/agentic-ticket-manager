"""
SLA rules — defines response and resolution time targets per priority level.

These are the thresholds the SLA monitor agent reasons against.
Keeping them here (not hardcoded in prompts) means you can tune them
for different clients or environments without touching agent logic.
"""

from datetime import timedelta

# SLA time limits per priority
# response_time: how long until first response is expected
# resolution_time: how long until the ticket should be fully resolved
SLA_POLICIES = {
    "Critical": {
        "response_time": timedelta(minutes=15),
        "resolution_time": timedelta(hours=4),
        "escalation_threshold": 0.75,  # Alert when 75% of time window used
        "description": "Production down or major security incident. All hands.",
    },
    "High": {
        "response_time": timedelta(hours=1),
        "resolution_time": timedelta(hours=8),
        "escalation_threshold": 0.75,
        "description": "Major feature broken, significant user impact.",
    },
    "Medium": {
        "response_time": timedelta(hours=4),
        "resolution_time": timedelta(hours=24),
        "escalation_threshold": 0.80,
        "description": "Partial degradation or workaround available.",
    },
    "Low": {
        "response_time": timedelta(hours=8),
        "resolution_time": timedelta(days=3),
        "escalation_threshold": 0.85,
        "description": "Minor issue, cosmetic, or feature request.",
    },
}

# Ticket categories and which teams handle them
ROUTING_RULES = {
    "network": {
        "team": "Infrastructure",
        "keywords": ["network", "connectivity", "vpn", "firewall", "dns", "bandwidth", "latency"],
    },
    "security": {
        "team": "Security Operations",
        "keywords": ["security", "breach", "unauthorized", "malware", "phishing", "access", "permission"],
    },
    "database": {
        "team": "Data Engineering",
        "keywords": ["database", "sql", "query", "replication", "backup", "data loss", "corruption"],
    },
    "application": {
        "team": "Application Engineering",
        "keywords": ["app", "api", "service", "deployment", "crash", "error", "exception", "timeout"],
    },
    "hardware": {
        "team": "IT Operations",
        "keywords": ["hardware", "disk", "memory", "cpu", "server", "device", "printer", "monitor"],
    },
    "authentication": {
        "team": "Identity & Access",
        "keywords": ["login", "password", "sso", "mfa", "ldap", "authentication", "account", "locked"],
    },
}


def get_sla_context() -> str:
    """Format SLA policies for injection into LLM prompts."""
    lines = ["SLA Policies by Priority:\n"]
    for priority, policy in SLA_POLICIES.items():
        rt = int(policy["response_time"].total_seconds() / 60)
        res = int(policy["resolution_time"].total_seconds() / 60)
        lines.append(f"{priority}:")
        lines.append(f"  Response required within: {rt} minutes")
        lines.append(f"  Resolution required within: {res} minutes")
        lines.append(f"  Context: {policy['description']}")
        lines.append("")
    return "\n".join(lines)


def get_routing_context() -> str:
    """Format routing rules for injection into LLM prompts."""
    lines = ["Team Routing Rules:\n"]
    for category, rule in ROUTING_RULES.items():
        lines.append(f"{category.title()} issues → {rule['team']}")
        lines.append(f"  Keywords: {', '.join(rule['keywords'])}")
        lines.append("")
    return "\n".join(lines)


def get_sla_limits(priority: str) -> dict:
    """Return raw timedelta limits for a given priority."""
    policy = SLA_POLICIES.get(priority, SLA_POLICIES["Medium"])
    return {
        "response_minutes": int(policy["response_time"].total_seconds() / 60),
        "resolution_minutes": int(policy["resolution_time"].total_seconds() / 60),
        "escalation_threshold": policy["escalation_threshold"],
    }
