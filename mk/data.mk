# data.mk: quotes from EODHD (config.toml [data]) and the clock QA gate.
.PHONY: data qa
data:                           ## download / refresh the configured quotes (cached, resumable)
	$(PY) -m amq.cli data
qa:                             ## clock QA gate on intraday series (payrolls spike 08:30 NY, reference lag 0)
	$(PY) -m amq.cli qa
