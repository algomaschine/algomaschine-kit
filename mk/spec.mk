# spec.mk: pre-registration. SPEC.md is frozen (hash + grid size) before any real walk-forward.
.PHONY: spec-lock spec-check spec-bump
spec-lock:                      ## freeze SPEC.md + the strategy grid (writes spec.lock)
	@grep -q "TODO" SPEC.md && { echo "SPEC.md still has TODOs: fill it before freezing"; exit 1; } || true
	$(PY) -m amq.cli spec-lock
spec-check:                     ## fail if SPEC.md or the grid changed since spec-lock
	$(PY) -m amq.cli spec-check
spec-bump:                      ## record a deliberate spec change (REASON="...") and re-freeze; the trial ledger keeps counting
	@test -n "$(REASON)" || { echo 'usage: make spec-bump REASON="why the spec changed"'; exit 1; }
	$(PY) -m amq.cli spec-bump "$(REASON)"
