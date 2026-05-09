# MOBIUS RENDER MESH LEDGER SPEC

Cycle: C-306
Status: Draft

## Purpose

Define the canonical ledger contract for the Mobius Render Mesh.

The Civic Protocol Ledger acts as the durable truth layer for:
- service registration
- heartbeat attestations
- GI state changes
- quorum events
- seal lifecycle events
- agent ownership declarations
- degraded/quarantined transitions

## Core Architecture

Render APIs produce signals.
The CRON Engine orchestrates heartbeats.
The Civic Protocol Ledger stores attested truth.
The Terminal displays operational state.
The Substrate defines semantic meaning.

## Proposed Ledger Events

- service_registered
- service_health_attested
- cron_heartbeat_attested
- gi_metric_recorded
- quorum_state_changed
- seal_candidate_evaluated
- seal_initiated
- service_quarantined
- operator_override_registered

## Required Mesh Components

1. Service Registry
2. CRON Engine
3. Shared Auth Contract
4. GI Stream
5. Agent Ownership Map
6. Escalation Ladder
7. Ledger Write Policy

## Agent Ownership Map

- ECHO → heartbeat + journal feed
- AUREA → integrity orchestration
- ATLAS → watchdog + threat scan
- ZEUS → verification + seal guard
- EVE → synthesis + ethics
- JADE → morale + cycle context
- HERMES → market/external signal layer
- URIEL → adversarial reasoning
- ZENITH → alternate-model verification

## Canonical Principle

Truth flows:
Canon → Ledger → UI

The ledger is the final attested source of truth for mesh state.
