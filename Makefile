PY ?= python3
export PYTHONPATH := src
TICKERS = VRT ETN NVT MOD HUBB GEV JCI TT SMCI POWL

.PHONY: all metrics offline notes demo eval test app

all: offline eval demo test   ## reproduce everything from the committed caches, no API key

metrics:          ## data/cache -> data/processed/*.csv (downloads only what is not cached)
	$(PY) -m verity.build_metrics

offline:          ## same, but never touch the network
	VERITY_OFFLINE=1 $(PY) -m verity.build_metrics

notes:            ## research, write and fact-check a note per company -> outputs/
	VERITY_OFFLINE=1 $(PY) -m verity.cli run $(TICKERS)

demo:             ## VRT note with 4 planted errors, to see the fact-check loop work
	VERITY_OFFLINE=1 $(PY) -m verity.cli run VRT --inject 4 --seed 3

eval:             ## all experiments -> eval/results/, docs/results.md, docs/figures/
	VERITY_OFFLINE=1 $(PY) -m eval.run_all

test:
	VERITY_OFFLINE=1 $(PY) -m pytest -q tests

app:
	streamlit run app/streamlit_app.py
