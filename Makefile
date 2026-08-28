# Convenience wrapper over the Python drivers in scripts/.
#
#   make test      run the regression suite
#   make mutation  check that every injected RTL fault is detected
#   make synth     synthesise and report area and timing
#   make all       all three, in the order a change should be checked in

PYTHON ?= python3
SEED   ?= 1
SCALE  ?= 1.0

.PHONY: all lint test mutation synth paths clean

all: lint test mutation synth

lint:
	$(PYTHON) scripts/run_regression.py --filter lint

test:
	$(PYTHON) scripts/run_regression.py --seed $(SEED) --scale $(SCALE)

mutation:
	$(PYTHON) scripts/run_regression.py --mutation

synth:
	$(PYTHON) scripts/synth.py

paths:
	$(PYTHON) scripts/synth.py --paths

clean:
	rm -rf build
