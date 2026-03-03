# Familiar - Development Makefile
# For local development and quick deploys to NAS

.PHONY: help dev dev-remote build deploy-dev deploy-frontend deploy-backend release-testflight deploy-device

help:
	@echo "Familiar Development Commands"
	@echo ""
	@echo "Local Development:"
	@echo "  make dev          - Start local dev (frontend + backend)"
	@echo "  make dev-remote   - Frontend dev server proxying to NAS backend"
	@echo ""
	@echo "Deploy to NAS:"
	@echo "  make deploy-dev      - Build & deploy everything (~30s)"
	@echo "  make deploy-frontend - Deploy frontend only"
	@echo "  make deploy-backend  - Deploy backend only"
	@echo ""
	@echo "iOS:"
	@echo "  make deploy-device      - Build & install to connected iPhone (~2 min)"
	@echo "  make release-testflight - Build & upload to TestFlight"

# Local development - runs frontend and backend locally
dev:
	@echo "Starting local development..."
	@echo "Run these in separate terminals:"
	@echo "  Terminal 1: docker compose up -d  (database + redis)"
	@echo "  Terminal 2: cd backend && make run"
	@echo "  Terminal 3: cd packages/web && pnpm dev"

# Frontend dev server proxying to remote NAS backend
dev-remote:
	cd packages/web && VITE_API_TARGET=http://openmediavault:4400 pnpm dev

# Build web frontend
build:
	pnpm --filter @familiar/web run build

# Quick deploy to NAS (build + rsync + restart)
deploy-dev:
	./scripts/deploy-dev.sh

# Deploy frontend only
deploy-frontend:
	./scripts/deploy-dev.sh --frontend-only

# Deploy backend only
deploy-backend:
	./scripts/deploy-dev.sh --backend-only

# Build and upload iOS app to TestFlight
release-testflight:
	cd packages/ios && ./scripts/release-testflight.sh

# Build and install iOS app directly to connected device
deploy-device:
	cd packages/ios && ./scripts/deploy-device.sh
