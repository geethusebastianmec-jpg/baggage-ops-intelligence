PYTHON := .venv/Scripts/python
PIP    := .venv/Scripts/pip

.PHONY: up down logs test demo install topics venv

# ── Infrastructure ────────────────────────────────────────────────────────────

up:
	docker compose up -d
	@echo "Waiting for services to be healthy..."
	@docker compose ps
	@echo ""
	@echo "Services:"
	@echo "  Redpanda Console  → http://localhost:8080"
	@echo "  Kafka bootstrap   → localhost:19092"
	@echo "  PostgreSQL        → localhost:5432  (baggage/baggage)"
	@echo "  Redis             → localhost:6379"

down:
	docker compose down

down-volumes:
	docker compose down -v

logs:
	docker compose logs -f

# ── Kafka topics ──────────────────────────────────────────────────────────────

topics:
	docker exec baggage_redpanda rpk topic create \
		ops.flights.delays \
		ops.flights.gate-changes \
		ops.flights.cancellations \
		ops.baggage.exceptions \
		ops.ramp.crew-status \
		ops.equipment.alerts \
		ops.decisions.conflicts \
		ops.decisions.resolved \
		ops.decisions.playbooks \
		ops.audit.actions \
		--partitions 4 \
		--replicas 1
	@echo "Kafka topics created."

# ── Python setup ─────────────────────────────────────────────────────────────

venv:
	python -m venv .venv
	@echo "venv created. Activate with: .venv/Scripts/activate (Windows) or source .venv/bin/activate (Unix)"

install: venv
	$(PIP) install -r requirements.txt

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

test-unit:
	$(PYTHON) -m pytest tests/ -v --tb=short -k "not scenario"

test-scenario:
	$(PYTHON) -m pytest tests/test_scenario.py -v --tb=short

# ── Demo ──────────────────────────────────────────────────────────────────────

demo:
	@echo "Starting Hub Crisis demo scenario..."
	$(PYTHON) demo/scenario_runner.py

dashboard:
	$(PYTHON) -m streamlit run demo/dashboard.py --server.port 8501

# ── Utility ───────────────────────────────────────────────────────────────────

shell-kafka:
	docker exec -it baggage_redpanda rpk topic list

shell-redis:
	docker exec -it baggage_redis redis-cli

shell-postgres:
	docker exec -it baggage_postgres psql -U baggage -d baggage_ops
