#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
#  AutoGen Team Builder — Uninstaller
# ══════════════════════════════════════════════════════════════════════════════

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
step()  { echo -e "\033[0;36m[→]${NC} $1"; }

echo ""
echo -e "${RED}${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${RED}${BOLD}║   🗑️  AutoGen Team Builder — Uninstaller     ║${NC}"
echo -e "${RED}${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Detect compose
if command -v docker compose &> /dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo "Docker Compose not found."
  exit 0
fi

echo -e "${YELLOW}This will stop the container and remove generated config files.${NC}"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 0
fi

echo ""

step "Stopping container..."
$COMPOSE_CMD down --remove-orphans 2>/dev/null || true
info "Container stopped"

step "Removing generated files..."
[ -f .env ] && rm -f .env && info "Removed .env"

echo ""
read -p "Also remove Docker image? (y/N) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
  step "Removing Docker image..."
  docker images --filter "reference=*autogen*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
  info "Image removed"
fi

echo ""
echo -e "${GREEN}${BOLD}✅ Uninstall complete.${NC}"
echo -e "   To reinstall: ${BOLD}bash install.sh${NC}"
echo ""
