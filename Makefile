.DEFAULT_GOAL := help
SERVICES := dispatch-api dispatch-worker

.PHONY: help up down test seed demo logs

help: ## Show available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

up: ## Build and start the local stack (docker compose + Moto)
	docker compose up -d --build
	@echo "waiting for dispatch-api..."
	@for i in $$(seq 1 60); do curl -sf localhost:8080/readyz >/dev/null && echo "ready: http://localhost:8080/docs" && exit 0; sleep 2; done; \
		echo "dispatch-api did not become ready"; docker compose logs --tail=50; exit 1

down: ## Stop the stack and delete its data
	docker compose down -v

test: ## Lint and test every service inside Docker
	@for s in $(SERVICES); do docker build --target test -t rescueops/$$s:test services/$$s || exit 1; done

seed: ## Register five ambulances across Lagos
	./scripts/seed-ambulances.sh

demo: ## Report an emergency and watch it get dispatched
	./scripts/demo.sh

logs: ## Tail service logs
	docker compose logs -f dispatch-api dispatch-worker
