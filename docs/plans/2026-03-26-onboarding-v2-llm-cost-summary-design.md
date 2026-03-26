# Onboarding V2 LLM Cost Summary Design

**Problem:** `onboarding_v2` currently records token usage for LLM stages, but it does not estimate or expose the final USD cost in a stable artifact.

**Goal:** Persist call-level and total LLM cost estimates for `onboarding_v2`, and expose the final summary as a run artifact and engine return field.

## Approach

Reuse the existing pricing model already used by the legacy onboarding flow instead of introducing a separate v2 pricing surface. `llm_runtime.py` will normalize richer usage data, including cached prompt tokens when present. `LlmUsageStore` will own cost estimation and summary persistence so the aggregation logic stays close to the append-only usage log.

At the end of a run, the engine will emit a `llm-usage-summary` JSON artifact containing totals, pricing metadata, and call records. This keeps the raw debug log intact while making the final cost visible from the artifact tree and the engine result payload.

## Data Shape

- Per call:
  - `input_tokens`
  - `output_tokens`
  - `cached_input_tokens`
  - `total_tokens`
  - `estimated_input_cost_usd`
  - `estimated_output_cost_usd`
  - `estimated_cached_input_cost_usd`
  - `estimated_total_cost_usd`
- Summary:
  - `totals`
  - `pricing`
  - `calls`

## Tradeoffs

- Reusing the legacy pricing table avoids config churn, but it means v2 pricing stays coupled to the shared onboarding pricing defaults.
- Writing the summary both under `debug/` and as an artifact duplicates the data slightly, but it gives us both an append-friendly debug log and a stable final artifact path.

## Validation

- Storage test proving usage append produces cost totals and pricing metadata.
- Engine test proving the final run result exposes the `llm-usage-summary` artifact path and the artifact payload contains the final total cost.
