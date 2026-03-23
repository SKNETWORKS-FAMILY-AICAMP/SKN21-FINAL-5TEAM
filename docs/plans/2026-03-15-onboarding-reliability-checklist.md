# Onboarding Reliability Demo Checklist

- Run `uv run pytest --noconftest chatbot/tests/onboarding/test_smoke_runner.py chatbot/tests/onboarding/test_overlay_generator.py chatbot/tests/onboarding/test_smoke_summary.py chatbot/tests/onboarding/test_orchestrator.py chatbot/tests/onboarding/test_retry_policy.py chatbot/tests/onboarding/test_slack_bridge.py chatbot/tests/onboarding/test_agent_integration.py chatbot/tests/onboarding/test_export_approval_contract.py chatbot/tests/onboarding/test_exporter.py chatbot/tests/onboarding/test_cli_runner.py chatbot/tests/onboarding/test_generator_rubric.py chatbot/tests/onboarding/test_generator_eval_runner.py chatbot/tests/onboarding/test_generator_eval_cli.py chatbot/tests/onboarding/test_generator_golden_fixtures.py chatbot/tests/onboarding/test_generator_golden_regression.py -v`
- Confirm `reports/smoke-results.json` and `reports/smoke-summary.json` are emitted for a completed run.
- Confirm `reports/diagnostic-report.json` is emitted for a failed validation run.
- Confirm `reports/export-metadata.json` is emitted after export approval.
- Use CLI output paths instead of guessing report locations during demos.
- Treat `human_review_required` as the correct stop state for structural failures.
