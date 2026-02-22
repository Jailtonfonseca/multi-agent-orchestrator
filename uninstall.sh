#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
#  AutoGen Enterprise — Uninstaller
#  Stops all containers, removes volumes, and cleans generated config files.
# ══════════════════════════════════════════════════════════════════════════════

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
step()    { echo -e "${CYAN}[→]${NC} $1"; }

echo ""
echo -e "${RED}${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${RED}${BOLD}║   🗑️  AutoGen Enterprise — Uninstaller       ║${NC}"
echo -e "${RED}${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Detect compose command
if command -v docker compose &> /dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo "Docker Compose not found. Nothing to uninstall."
  exit 0
fi

# ── Confirm ──────────────────────────────────────────────────────────────────
echo -e "${YELLOW}This will:${NC}"
echo "  • Stop and remove all containers"
echo "  • Remove Docker volumes (database data will be LOST)"
echo "  • Remove generated .env and docker-compose.override.yml"
echo ""
read -p "Are you sure? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Cancelled."
  exit 0
fi

echo ""

# ── Stop containers ──────────────────────────────────────────────────────────
step "Stopping containers..."
$COMPOSE_CMD down --remove-orphans 2>/dev/null || true
info "Containers stopped"

# ── Remove volumes ───────────────────────────────────────────────────────────
step "Removing Docker volumes..."
$COMPOSE_CMD down -v 2>/dev/null || true
info "Volumes removed"

# ── Remove generated files ───────────────────────────────────────────────────
step "Cleaning generated config files..."

[ -f .env ] && rm -f .env && info "Removed .env"
[ -f docker-compose.override.yml ] && rm -f docker-compose.override.yml && info "Removed docker-compose.override.yml"

# ── Remove Docker images (optional) ──────────────────────────────────────────
echo ""
read -p "Also remove built Docker images? (y/N) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
  step "Removing Docker images..."
  PROJECT_NAME=$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]//g')
  docker images --filter "reference=*${PROJECT_NAME}*" -q 2>/dev/null | xargs -r docker rmi -f 2>/dev/null || true
  # Also try with the directory name as-is
  docker images -q --filter "label=com.docker.compose.project" 2>/dev/null | head -20 | xargs -r docker rmi -f 2>/dev/null || true
  info "Images removed"
fi

echo ""
echo -e "${GREEN}${BOLD}✅ Uninstall complete.${NC}"
echo -e "   To reinstall: ${BOLD}bash install.sh${NC}"
echo ""
