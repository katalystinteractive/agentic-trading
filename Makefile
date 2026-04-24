.PHONY: test import-health neural-artifacts quality

PYTHON ?= python3

test:
	$(PYTHON) -m pytest -q

import-health:
	$(PYTHON) -m pytest tests/test_tool_imports.py -q

neural-artifacts:
	$(PYTHON) tools/neural_artifact_validator.py

quality: test import-health
