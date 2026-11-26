.PHONY: check validate plugin-validate test python-test shellcheck

JOBS ?= $(shell nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)

# Everything CI runs. `claude` must be on PATH for plugin-validate.
check: validate plugin-validate shellcheck test python-test

validate:
	bash scripts/validate --verbose

plugin-validate:
	claude plugin validate .

shellcheck:
	shellcheck -x -S warning scripts/validate skills/*/scripts/*.sh

test:
	bats --jobs $(JOBS) tests

python-test:
	python3 scripts/run-python-tests tests/python --jobs $(JOBS)
