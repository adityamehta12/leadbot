.PHONY: dev build lint tf-init tf-plan tf-apply migrate

dev:
	cd backend && python3 -m uvicorn app:app --reload --host 0.0.0.0 --port 8000

build:
	docker build -f backend/Dockerfile -t leadbot-api .

lint:
	ruff check backend/

migrate:
	cd backend && python3 -m alembic upgrade head

migrate-down:
	cd backend && python3 -m alembic downgrade -1

tf-init:
	cd infra && terraform init

tf-plan:
	cd infra && terraform plan

tf-apply:
	cd infra && terraform apply
