# Ricky_1 — common developer shortcuts (optional)
.PHONY: status light-status local-start

status light-status:
	@python scripts/check_light_ready.py

local-start:
	@bash deploy/local_startup.sh
