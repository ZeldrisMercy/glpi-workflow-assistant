# Actual API and text contract

| Route | Role |
|---|---|
| `GET /health` | Version/health |
| `GET /api/status` | Local setup state |
| `POST /api/parse` | Parse a closure |
| `POST /api/parse-batch` | Separate explicit ticket blocks |
| `POST /api/plan` | Validate ticket/text/evidence map and create Dry Run |
| `POST /api/execute` | Apply a previously reviewed plan with bound files |
| `POST /api/bridge/pair-code`, `/api/bridge/pair` | Local pairing |
| `POST /api/bridge/handoff` | Paired structured handoff |
| `GET /api/workbench` | Operator queue/monitor state |

See the real routes in `main.py`/`workbench.py`; proactive ticket creation is not present.

Closure fields include `[GLPI_ASSISTANT:ID]`, `[TAREFA:T01]` blocks, modality, level, duration, state and optional `[EVIDÊNCIA:E01]`. Full closure semantics are T01 Problem reported, T02 Problem identified, T03 Diagnosis, T04 Solution applied, T05 Customer validation. Only report a customer confirmation when provided.

The exact parser accepts additional/continuation tasks; the prompt determines the documentation standard. Use `demo/fixtures/formalization.txt` for a parseable synthetic example and `package/usr/lib/glpi-assistant/app/PROMPT_FORMALIZACAO.md` for the sanitized prompt.
