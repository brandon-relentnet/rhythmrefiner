SHELL := /bin/bash

.PHONY: backend-dev backend-prod frontend-dev frontend-build dev-up prod-up

backend-dev:
	set -a; [ -f .env ] && . .env; set +a; \
	uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

backend-prod:
	set -a; [ -f .env ] && . .env; set +a; \
	uvicorn backend.main:app --host 192.168.86.81 --port 11221

frontend-dev:
	cd frontend && npm install && npm run dev -- --host --port 3000

frontend-build:
	cd frontend && npm install && npm run build

dev-up:
	$(MAKE) -j2 backend-dev frontend-dev

prod-up:
	$(MAKE) -j2 backend-prod frontend-build
