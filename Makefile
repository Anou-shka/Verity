PY ?= python3
export PYTHONPATH := src

.PHONY: metrics test offline

metrics:          ## data/cache -> data/processed/*.csv (downloads only what is not cached)
	$(PY) -m verity.build_metrics

offline:          ## same, but never touch the network
	VERITY_OFFLINE=1 $(PY) -m verity.build_metrics

test:
	$(PY) -m pytest -q tests
