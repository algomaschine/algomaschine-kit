# project.mk: included by every project's Makefile. `make help` lists the targets.
include $(dir $(lastword $(MAKEFILE_LIST)))common.mk
include $(KIT)/mk/data.mk $(KIT)/mk/spec.mk $(KIT)/mk/research.mk $(KIT)/mk/web.mk $(KIT)/mk/rust.mk
.DEFAULT_GOAL := help
.PHONY: help backup
help:                           ## this list
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:[^#]*## /\t/' | sort | awk -F'\t' '{printf "  make %-14s %s\n", $$1, $$2}'
backup:                         ## timestamped tarball of the project (outputs pickles excluded) next to it
	tar --exclude='__pycache__' --exclude='$(OUT)/*.pkl' -czf ../$(PROJECT)_backup_$$(date +%Y%m%d-%H%M%S).tar.gz -C .. $(PROJECT)
