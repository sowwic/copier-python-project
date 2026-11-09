SHELL := /bin/bash

REMOTE = origin

# `make tag v1`: the word after `tag` is the tag name (NEW=v1 also works)
ifeq ($(firstword $(MAKECMDGOALS)),tag)
NEW ?= $(word 2,$(MAKECMDGOALS))
# Swallow the tag name so make does not treat it as a target
$(eval $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS)):;@:)
endif

# Colors
BLUE := \033[34m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
MAGENTA := \033[35m
CYAN := \033[36m
RESET := \033[0m

# Banner helper
define banner
	@printf "$(CYAN)==>$(RESET) $(1)\n"
endef

.PHONY: help
help: ## Show this help message
	@echo "Available make targets:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS=":.*?##"}; {printf "  %-15s %s\n", $$1, $$2}'
	@echo ""

.PHONY: tag
tag: ## Create tag (e.g. make tag v1) at HEAD, or move it if it exists, and push it
	@if [ -z "$(NEW)" ]; then \
		printf "$(RED)Usage: make tag <tag>  (e.g. make tag v1)$(RESET)\n"; \
		exit 1; \
	fi
	@if git rev-parse -q --verify "refs/tags/$(NEW)" >/dev/null; then \
		printf "$(CYAN)==>$(RESET) Moving tag $(YELLOW)$(NEW)$(RESET) to $$(git rev-parse --short HEAD)\n"; \
	else \
		printf "$(CYAN)==>$(RESET) Creating tag $(YELLOW)$(NEW)$(RESET) at $$(git rev-parse --short HEAD)\n"; \
	fi
	@git tag -f "$(NEW)"
	@git push --force $(REMOTE) "refs/tags/$(NEW)"
	@printf "$(GREEN)Tag $(NEW) now points to $$(git rev-parse --short HEAD).$(RESET)\n"
