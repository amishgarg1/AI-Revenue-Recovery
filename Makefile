# RecoverOS
#
# `make demo` is the one command a judge needs. Everything below runs on Linux,
# macOS and Windows (Git Bash / WSL) with no shell-specific syntax — the earlier
# version used `set PYTHONPATH=$(cd)`, which is neither valid Make nor valid
# POSIX sh, and failed everywhere.

PYTHON  ?= python
BACKEND := backend
export PYTHONPATH := $(BACKEND)

.PHONY: help demo install seed run-batch report verify voice webhook sensitivity plan test api web build clean

help:
	@echo "RecoverOS"
	@echo ""
	@echo "  make demo      seed, run the batch, regenerate EVALUATION.md"
	@echo "  make install   install backend and frontend dependencies"
	@echo "  make test      run the test suite"
	@echo "  make verify    recompute the audit chain from genesis"
	@echo "  make voice     render the Hinglish voice scripts to audio"
	@echo "  make webhook   post a real Razorpay payment.failed at the running API"
	@echo "  make sensitivity  sweep every assumption and regenerate docs/sensitivity.md"
	@echo "  make plan      plan the sample backlog in examples/"
	@echo "  make api       backend on http://localhost:8000"
	@echo "  make web       dashboard on http://localhost:3000"
	@echo ""
	@echo "No API keys are required. Without them the demo runs on"
	@echo "deterministic templates and simulated payment links, and says so."

demo: seed run-batch report sensitivity
	@echo ""
	@echo "Done. Read EVALUATION.md, or run 'make api' and 'make web' for the dashboard."

install:
	$(PYTHON) -m pip install -r $(BACKEND)/requirements.txt
	cd frontend && npm install

seed:
	$(PYTHON) $(BACKEND)/scripts/seed.py

run-batch:
	$(PYTHON) $(BACKEND)/scripts/run_batch.py

report:
	$(PYTHON) $(BACKEND)/scripts/make_report.py

sensitivity:
	$(PYTHON) $(BACKEND)/scripts/sensitivity.py

plan:
	$(PYTHON) $(BACKEND)/scripts/plan.py examples/failed_payments.csv

verify:
	$(PYTHON) $(BACKEND)/scripts/verify_ledger.py

voice:
	$(PYTHON) $(BACKEND)/scripts/render_voice.py

# Needs 'make api' running in another shell.
webhook:
	$(PYTHON) $(BACKEND)/scripts/send_webhook.py

test:
	$(PYTHON) -m pytest $(BACKEND)/tests -q

api:
	$(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

clean:
	rm -rf $(BACKEND)/**/__pycache__ .pytest_cache frontend/.next
