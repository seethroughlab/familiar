# Familiar - Development Makefile
# For local development and quick deploys to NAS

.PHONY: help dev dev-remote build deploy-dev deploy-frontend deploy-backend release-testflight deploy-device smoke-test-docker

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
	@echo ""
	@echo "Testing:"
	@echo "  make smoke-test-docker  - Run CLAP smoke test in Docker (~1.5GB model download on first run)"

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

# The phone app is built in the familiar-apple repo (ADR-0001). These two targets stay, and say so,
# rather than being deleted: `make release-testflight` is muscle memory, and "No rule to make target"
# would send you looking for what broke instead of telling you where the app went.
release-testflight:
	@echo "The iOS app ships from the familiar-apple repo now — the Capacitor app is retired (ADR-0001)."
	@echo ""
	@echo "    cd ../familiar-apple && ./scripts/release-testflight.sh"
	@echo ""
	@echo "That script archives Familiar-iOS, signs it, and uploads to the same"
	@echo "App Store Connect record (com.familiar.player). First build from it: 1.2 (14)."
	@exit 1

deploy-device:
	@echo "The iOS app ships from the familiar-apple repo now — the Capacitor app is retired (ADR-0001)."
	@echo ""
	@echo "There is no deploy-device script there yet. Build and install with:"
	@echo ""
	@echo "    cd ../familiar-apple"
	@echo "    xcodebuild -project Familiar.xcodeproj -scheme Familiar-iOS \\"
	@echo "      -destination 'generic/platform=iOS' -skipPackagePluginValidation build"
	@echo "    xcrun devicectl device install app --device <udid> <built .app>"
	@exit 1

# Run CLAP smoke test inside Docker (downloads ~1.5GB model on first run)
smoke-test-docker:
	docker build -t familiar-smoke-test -f docker/Dockerfile . && \
	docker run --rm -v familiar-hf-cache:/root/.cache/huggingface \
		familiar-smoke-test python /app/scripts/smoke_test_clap.py
