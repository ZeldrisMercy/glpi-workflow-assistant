# Synthetic demonstration data

`demo/fixtures/formalization.txt` is a parseable five-task example for ticket 900001. Screenshot API fixtures live in the capture script and use Alex Exemplo, Empresa Aurora and `glpi.example.invalid`. They cannot send messages or write to GLPI.

Regression fixtures contain syntactically valid phone numbers and identifiers so normalization can be tested. They are offline examples, not authorized destinations. No production databases, session material or historical QA reports are shipped.

The capture API response for Dry Run and execution is simulated; the actual parser and interface are used. Do not interpret a simulated success receipt as backend integration validation.
