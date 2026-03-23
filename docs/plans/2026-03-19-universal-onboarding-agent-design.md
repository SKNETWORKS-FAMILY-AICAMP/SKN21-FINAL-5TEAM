# Universal Onboarding Agent Design

## Goal

Build a contract-driven onboarding agent that can analyze framework variants, generate onboarding artifacts conservatively, validate them in a runtime workspace, and attempt targeted repairs before escalating.

## Implemented Shape

- Site analysis emits typed integration contracts for backend, frontend, chat auth, product adapter, and order adapter.
- Patch planning uses framework strategy selection plus an allowlist derived from the active integration contract.
- Template generation stays repo-local, uses framework-specific auth bridge code, and writes frontend widgets only under approved paths.
- Validation rejects route wiring drift, missing import targets, invalid frontend mount placement, and widget paths outside `frontend/src`.
- The orchestrator classifies failures, writes recovery artifacts, applies targeted repair actions, retries validation, and exports recovery provenance.

## Key Constraints

- Generated targets must stay within strategy-approved files.
- Frontend mount patches must remain framework-safe.
- Repo-external imports are not allowed in generated auth templates.
- Repair attempts must be explicit, classified, and observable in run artifacts.

## Regression Coverage

- `food` Django/React fixtures enforce auth source and route registration targeting under `users` plus the project route entrypoint.
- `bilyeo` Flask/Vue fixtures enforce blueprint registration plus Vue shell-safe mount targeting.
- Generator regression fixtures now cover strategy shape and repeated recovery cases for `food-run-003` and `food-run-004`.

## Verification Baseline

- Focused onboarding suite: `160 passed`
- Syntax check: `uv run python -m py_compile chatbot/src/onboarding/*.py`

