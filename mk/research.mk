# research.mk: the review gate, the walk-forward and the report. The walk-forward refuses to run without a
# frozen spec (spec.lock) and a passed review ($(OUT)/review_passed.json).
.PHONY: review walkforward report audit all status logs
review: spec-check              ## pre-run review: causality, purging, timing, sign-flip null, planted effect
	$(call capped,review,amq.cli review)
	$(call wait,review)
walkforward: spec-check         ## auto-calibrated walk-forward on real data (needs the passed review)
	@test -f $(OUT)/review_passed.json || { echo "review has not passed: make review"; exit 3; }
	$(call capped,walkforward,amq.cli walkforward)
	$(call wait,walkforward)
report:                         ## results.json for the dashboard (PBO, CPCV, DSR with the trial ledger)
	$(call capped,report,amq.cli report)
	$(call wait,report)
audit:                          ## the too-good-to-be-true audit: luck, search, market, look-ahead, fragility
	$(call capped,audit,amq.cli audit)
	$(call wait,audit)
all: data qa review walkforward report audit   ## the whole pipeline, in order
status:                         ## what is running, where it is, server resources
	@systemctl --user list-units --type=service --no-pager | grep -E "$(UNIT)" || echo "no $(UNIT) jobs running"
	@cat $(OUT)/status.json 2>/dev/null; echo; tail -1 $(OUT)/monitor_*.log 2>/dev/null || true
logs:                           ## follow the logs
	tail -f $(OUT)/*.log
