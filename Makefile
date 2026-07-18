.PHONY: install install-ui install-llm doctor test check

install:
	python -m pip install -e .

install-ui:
	python -m pip install -e '.[ui]'

install-llm:
	python -m pip install -e '.[llm]'

doctor:
	python scripts/doctor.py

test:
	python -m unittest discover -s tests/unit

check: test
	git diff --check
