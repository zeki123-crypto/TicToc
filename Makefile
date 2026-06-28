.PHONY: help install run lint format up down logs clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies
	pip install -r requirements.txt

run: ## Run the bot locally
	python -m app

up: ## Start the bot + Redis via docker compose
	docker compose up -d --build

down: ## Stop all services
	docker compose down

logs: ## Tail bot logs
	docker compose logs -f bot

clean: ## Remove downloaded media and caches
	rm -rf downloads/* __pycache__ .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
