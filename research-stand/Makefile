PY ?= python
CONFIG ?= configs/experiment.yaml

.PHONY: help up down smoke experiment analyze all local calibrate

help:
	@echo "up         - поднять SUT в Docker Compose"
	@echo "down       - остановить стек"
	@echo "smoke      - smoke-тест (HTTP + WebGL + метрики) в контейнере"
	@echo "experiment - полный план прогонов"
	@echo "analyze    - статистика и графики"
	@echo "all        - smoke + experiment + analyze"
	@echo "local      - прогон без Docker (Windows-friendly)"
	@echo "calibrate  - калибровка пустой сцены"

up:
	docker compose up -d --build sut

down:
	docker compose --profile run --profile analysis down -v

smoke: up
	docker compose run --rm --entrypoint python runner scripts/smoke.py --base-url http://sut

experiment: up
	$(PY) runner/run_experiment.py --mode docker --config $(CONFIG)

analyze:
	$(PY) analysis/analyze.py

local:
	$(PY) runner/run_experiment.py --mode local --config $(CONFIG)

calibrate:
	$(PY) runner/run_experiment.py --mode local --config configs/calibration.yaml --force

all: smoke experiment analyze
