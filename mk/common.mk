# common.mk: paths, interpreter, resource caps, and the capped-job runner every heavy target uses.
KIT      ?= $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
PY       ?= $(shell command -v python3.11 >/dev/null 2>&1 && echo python3.11 || echo python3)
UV       ?= $(HOME)/.local/bin/uv
PROJECT  ?= $(notdir $(CURDIR))
OUT      ?= outputs
UNIT     ?= amq-$(PROJECT)
CPU      ?= 200%
MEM      ?= 4G
NICE     ?= 15
export PYTHONPATH := $(CURDIR):$(KIT)$(if $(PYTHONPATH),:$(PYTHONPATH))
export AMQ_OUT := $(abspath $(OUT))
export AMQ_DATA ?= $(abspath data)

# $(call capped,<job>,<python -m module args>): run as a systemd --user service (survives logout with
# lingering), capped, niced, logged to $(OUT)/<job>.log, with the resource monitor attached.
define capped
	@mkdir -p $(AMQ_OUT)
	systemd-run --user --unit=$(UNIT)-$(1) --collect -p CPUQuota=$(CPU) -p MemoryHigh=$(MEM) -p MemoryMax=$(MEM) \
	  -p Nice=$(NICE) -p IOSchedulingClass=idle -p WorkingDirectory=$(CURDIR) \
	  -E PYTHONPATH=$(PYTHONPATH) -E AMQ_OUT=$(AMQ_OUT) -E AMQ_DATA=$(AMQ_DATA) -E PYTHONUNBUFFERED=1 -E PYTHONWARNINGS=ignore \
	  -E OMP_NUM_THREADS=2 -E OPENBLAS_NUM_THREADS=2 -E RAYON_NUM_THREADS=2 \
	  -p StandardOutput=append:$(AMQ_OUT)/$(1).log -p StandardError=append:$(AMQ_OUT)/$(1).log $(PY) -m $(2)
	-systemd-run --user --unit=$(UNIT)-$(1)-monitor --collect -p CPUQuota=10% -p MemoryMax=300M -p WorkingDirectory=$(CURDIR) \
	  -E PYTHONPATH=$(PYTHONPATH) -E AMQ_OUT=$(AMQ_OUT) $(PY) -m amq.ops.monitor $(UNIT)-$(1).service
	@echo "started $(UNIT)-$(1): make status | tail -f $(OUT)/$(1).log"
endef

# $(call wait,<job>): block until the capped job finishes
define wait
	@while systemctl --user is-active --quiet $(UNIT)-$(1); do sleep 10; done; tail -5 $(AMQ_OUT)/$(1).log
endef
