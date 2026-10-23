# web.mk: the AlgoMaschine dashboard for this project, on a free port, behind a secret token.
.PHONY: serve unserve url
serve:                          ## start the dashboard (systemd --user, restarts on failure)
	@mkdir -p .amq $(AMQ_OUT)
	@test -f .amq/token || $(PY) -c "import secrets; print(secrets.token_urlsafe(18))" > .amq/token
	@test -f .amq/port || $(PY) -c "import socket; s=socket.socket(); s.bind(('',0)); print(s.getsockname()[1])" > .amq/port
	-systemctl --user stop $(UNIT)-web 2>/dev/null
	systemd-run --user --unit=$(UNIT)-web -p Restart=always -p CPUQuota=100% -p MemoryMax=1G -p WorkingDirectory=$(CURDIR) \
	  -E PYTHONPATH=$(PYTHONPATH) -E AMQ_OUT=$(AMQ_OUT) -E AMQ_TOKEN=$$(cat .amq/token) \
	  $(dir $(PY))uvicorn amq.report.app:app --host 0.0.0.0 --port $$(cat .amq/port) --log-level warning
	@$(MAKE) --no-print-directory url
unserve:                        ## stop the dashboard
	systemctl --user stop $(UNIT)-web
url:                            ## print the dashboard URL
	@echo "http://$$(hostname -I | awk '{print $$1}'):$$(cat .amq/port)/$$(cat .amq/token)/"
