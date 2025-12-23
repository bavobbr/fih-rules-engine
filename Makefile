PY=.venv/bin/python

.PHONY: install dev-install api web admin evals db-clean ingest-preview test fmt lint

install:
	$(PY) -m pip install -r requirements.txt

dev-install:
	$(PY) -m pip install -r requirements-dev.txt
	$(PY) -m pip install pre-commit ruff black pytest

# --- Public Services ---
api:
	$(PY) -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload

# --- Admin Operations ---
admin:
	$(PY) -m streamlit run Query.py

admin-debug:
	$(PY) -m streamlit run Query.py --logger.level=debug

evals:
	$(PY) -m evals.evaluate

db-clean:
	$(PY) -m scripts.cloudsql_truncate_table

ingest-preview:
	$(PY) -m scripts.export_chunks_vertex

# --- Development ---
test:
	pytest -q || true

fmt:
	black .
	ruff check --fix .

lint:
	ruff check .
	black --check .
