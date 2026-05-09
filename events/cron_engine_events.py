# Mobius CRON Engine — Ledger Event Types
# EPICON: C-306 / AUREA / cron-engine-events
# CC0 Public Domain

CRON_EVENT_TYPES = {

    "cron_heartbeat": {
        "description": "CRON Engine fired and completed one pulse cycle",
        "required_fields": ["cycle", "gi", "agent_activations", "ts"],
        "ledger_write": True,
        "frequency": "every_5_min",
    },

    "service_registered": {
        "description": "A Render service registered in the service registry",
        "required_fields": ["service_id", "owner_agent", "url", "tier"],
        "ledger_write": True,
        "frequency": "on_change",
    },
    "service_health_attested": {
        "description": "A service responded healthy to a health check",
        "required_fields": ["service_id", "health_path", "status_code", "latency_ms"],
        "ledger_write": False,
        "frequency": "every_5_min",
    },
    "service_degraded": {
        "description": "A service failed health check or returned unexpected state",
        "required_fields": ["service_id", "error", "consecutive_failures"],
        "ledger_write": True,
        "frequency": "on_event",
    },

    "agent_activated": {
        "description": "An agent's activation condition was met and it ran",
        "required_fields": ["agent_id", "tier", "trigger", "cost_usd"],
        "ledger_write": True,
        "frequency": "on_event",
    },
    "agent_gated": {
        "description": "Agent activation suppressed — budget or condition not met",
        "required_fields": ["agent_id", "tier", "reason"],
        "ledger_write": True,
        "frequency": "on_event",
    },

    "escalation_state_changed": {
        "description": "System moved to a new escalation tier",
        "required_fields": ["from_state", "to_state", "trigger", "gi"],
        "ledger_write": True,
        "frequency": "on_event",
    },
    "thought_broker_triggered": {
        "description": "thought-broker /v1/loop/start called for deliberation",
        "required_fields": ["trigger_condition", "loop_id", "agents_involved"],
        "ledger_write": True,
        "frequency": "on_event",
    },
    "thought_broker_consensus": {
        "description": "thought-broker returned consensus result",
        "required_fields": ["loop_id", "verdict", "confidence", "dissents"],
        "ledger_write": True,
        "frequency": "on_event",
    },

    "budget_warning": {
        "description": "Daily LLM budget >80% consumed",
        "required_fields": ["spent_usd", "limit_usd", "cycle"],
        "ledger_write": True,
        "frequency": "on_event",
    },
    "budget_exhausted": {
        "description": "Daily LLM budget reached — all Tier 1-3 agents gated",
        "required_fields": ["spent_usd", "limit_usd", "gated_agents"],
        "ledger_write": True,
        "frequency": "on_event",
    },
}
