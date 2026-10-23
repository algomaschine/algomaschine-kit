# rust.mk: build and install the relay_core accelerator (identical results to the Python references).
.PHONY: rust bench
rust:                           ## build relay_core with maturin and install it into $(PY)'s environment
	cd $(KIT)/rust/relay_core && PATH=$(HOME)/.cargo/bin:$$PATH $(dir $(PY))maturin build --release -i $(PY)
	$(UV) pip install --python $(PY) --reinstall $$(ls -t $(KIT)/rust/relay_core/target/wheels/*.whl | head -1)
bench:                          ## Rust vs Python equality + speed on this machine
	$(PY) -m amq.ops.bench
