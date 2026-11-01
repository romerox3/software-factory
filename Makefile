EXECUTORS := claude-code codex opencode mini-swe-agent
UV := uv run --locked

.PHONY: check

check:
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) check-jsonschema --check-metaschema schemas/*.json
	@set -e; for n in $(EXECUTORS); do \
		$(UV) check-jsonschema --schemafile schemas/executor-input.schema.json examples/executor/$$n.input.json; \
		$(UV) check-jsonschema --schemafile schemas/executor-output.schema.json examples/executor/$$n.output.json; \
	done
	$(UV) pytest -q
