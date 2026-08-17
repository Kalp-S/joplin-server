#!/usr/bin/env bash
# =============================================================================
# Joplin Server & Sync Service — Automated Integration Test Runner
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}====================================================${NC}"
echo -e "${BLUE}  Running Joplin Server & Sync Integration Tests    ${NC}"
echo -e "${BLUE}====================================================${NC}"

cd "${ROOT_DIR}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 is required to run the test suite.${NC}" >&2
    exit 1
fi

python3 tests/test_sync_service.py

echo -e "\n${GREEN}✔ All Joplin integration and sync tests passed successfully!${NC}"
