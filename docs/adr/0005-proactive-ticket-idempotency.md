# ADR 0005 — Idempotency for proactive creation

**Status:** Proposed

## Context
Criação automática pode abrir tickets duplicados em retries, refresh, replay ou eventos repetidos.

## Decision
Antes do POST, gerar uma correlation key/fingerprint estável e consultar estado local/remoto quando aplicável.

## Consequence
O sistema deve preferir bloquear e pedir revisão a criar silenciosamente um segundo ticket.
