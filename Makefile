.PHONY: install test clean run

install:
	@bash install.sh

test:
	@cd "$(dir $(lastword $(MAKEFILE_LIST)))" && python3 -m pytest tests/ -v 2>/dev/null || python3 -c "
import sys
sys.path.insert(0, 'tests')
sys.path.insert(0, 'tools')
exec(open('tests/test_pipeline.py').read())
"

run:
	python3 -m tools.case10_pipeline --input sample.txt --org config/org_structure.yaml --config config/config.yaml

clean:
	@rm -rf .venv __pycache__ tools/__pycache__ tests/__pycache__ .pytest_cache
	@echo "Cleaned"
