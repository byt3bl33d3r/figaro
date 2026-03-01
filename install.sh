#!/usr/bin/env bash
set -euo pipefail

# Figaro install script
# Usage:
#   ./install.sh                                  # install & start (defaults to prod-local)
#   ./install.sh [up] dev|prod-local|prod         # select overlay
#   ./install.sh build <overlay>                   # build images without starting
#   ./install.sh down <overlay>                    # stop services
#   ./install.sh down -v <overlay>                 # stop and remove all data
#   ./install.sh scale worker=4 <overlay>          # scale services
#   curl -fsSL .../install.sh | bash              # piped: clones repo first
#   curl ... | bash -s -- dev                     # piped with overlay argument

REPO_URL="https://github.com/byt3bl33d3r/figaro.git"
COMMAND=""
OVERLAY=""
SCALE_ARGS=()
DOWN_ARGS=()
VALID_OVERLAYS="dev prod-local prod"

# ---------- helpers ----------

info()  { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
warn()  { printf '\033[1;33m==> WARNING: %s\033[0m\n' "$*"; }
error() { printf '\033[1;31m==> ERROR: %s\033[0m\n' "$*" >&2; }
die()   { error "$@"; exit 1; }

# ---------- argument parsing ----------

is_overlay() {
    for valid in $VALID_OVERLAYS; do
        if [[ "$1" == "$valid" ]]; then return 0; fi
    done
    return 1
}

usage() {
    cat <<'EOF'
Usage: ./install.sh [command] [options]

Commands:
  up [overlay]                        Install and start services (default)
  build <overlay>                     Build images without starting
  down [-v] <overlay>                 Stop services (-v to remove all data)
  scale SERVICE=NUM ... <overlay>     Scale services (e.g. worker=4 supervisor=3)
  help                                Show this help message

Overlays:
  prod-local    Ports bound to 127.0.0.1 (default)
  dev           Localhost ports + desktop service for testing VNC
  prod          Ports bound to 0.0.0.0 (requires confirmation)

Examples:
  ./install.sh                       # start with prod-local overlay
  ./install.sh dev                   # start with dev overlay
  ./install.sh build prod-local       # build images only
  ./install.sh down prod-local       # stop services
  ./install.sh down -v prod-local    # stop and remove all data
  ./install.sh scale worker=4 prod-local  # scale workers to 4
  curl -fsSL .../install.sh | bash   # piped install (clones repo first)
EOF
}

parse_args() {
    if [[ $# -eq 0 ]]; then
        COMMAND="up"
        OVERLAY="prod-local"
        return
    fi

    case "$1" in
        help|-h|--help)
            usage
            exit 0
            ;;
        up)
            COMMAND="up"
            OVERLAY="prod-local"
            shift
            if [[ $# -gt 0 ]] && is_overlay "$1"; then
                OVERLAY="$1"
            elif [[ $# -gt 0 ]]; then
                die "Invalid overlay '$1'. Must be one of: $VALID_OVERLAYS"
            fi
            ;;
        build)
            COMMAND="build"
            shift
            if [[ $# -gt 0 ]] && is_overlay "$1"; then
                OVERLAY="$1"
            else
                die "Overlay required. Usage: ./install.sh build <dev|prod-local|prod>"
            fi
            ;;
        down)
            COMMAND="down"
            shift
            while [[ $# -gt 0 ]]; do
                if [[ "$1" == "-v" ]]; then
                    DOWN_ARGS+=("-v")
                elif is_overlay "$1"; then
                    OVERLAY="$1"
                else
                    die "Unknown argument '$1' for 'down'"
                fi
                shift
            done
            if [[ -z "$OVERLAY" ]]; then
                die "Overlay required. Usage: ./install.sh down [-v] <dev|prod-local|prod>"
            fi
            ;;
        scale)
            COMMAND="scale"
            shift
            if [[ $# -eq 0 ]]; then
                die "Usage: ./install.sh scale SERVICE=NUM ... <dev|prod-local|prod>"
            fi
            while [[ $# -gt 0 ]]; do
                if is_overlay "$1"; then
                    OVERLAY="$1"
                elif [[ "$1" == *=* ]]; then
                    SCALE_ARGS+=("--scale" "$1")
                else
                    die "Invalid scale argument '$1'. Use SERVICE=NUM format (e.g. worker=4)"
                fi
                shift
            done
            if [[ -z "$OVERLAY" ]]; then
                die "Overlay required. Usage: ./install.sh scale SERVICE=NUM ... <dev|prod-local|prod>"
            fi
            if [[ ${#SCALE_ARGS[@]} -eq 0 ]]; then
                die "No scale arguments provided. Usage: ./install.sh scale worker=4 supervisor=3 <dev|prod-local|prod>"
            fi
            ;;
        *)
            if is_overlay "$1"; then
                COMMAND="up"
                OVERLAY="$1"
            else
                die "Unknown command '$1'. Usage: ./install.sh [up|build|down|scale] [overlay]"
            fi
            ;;
    esac
}

parse_args "$@"

is_interactive() { [[ -t 0 ]]; }

prompt_continue() {
    if ! is_interactive; then return 0; fi
    local msg="${1:-Continue?}"
    read -rp "$msg [Y/n] " ans
    [[ -z "$ans" || "$ans" =~ ^[Yy] ]]
}

detect_os() {
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux)  echo "linux" ;;
        *)      die "Unsupported OS: $(uname -s)" ;;
    esac
}

# ---------- Docker installation ----------

install_docker_macos() {
    if command -v docker &>/dev/null; then
        info "Docker already installed"
        return 0
    fi

    die "Docker is not installed. Download Docker Desktop from https://docs.docker.com/desktop/setup/install/mac-install/ and re-run this script."
}

install_docker_linux() {
    if command -v docker &>/dev/null; then
        info "Docker already installed"
        return 0
    fi

    info "Installing Docker via get.docker.com..."
    curl -fsSL https://get.docker.com | sh

    if ! groups "$USER" | grep -q docker; then
        info "Adding $USER to the docker group..."
        sudo usermod -aG docker "$USER"
        warn "You may need to log out and back in for group changes to take effect."
        warn "If docker commands fail after install, run: newgrp docker"
    fi
}

ensure_docker() {
    local os="$1"
    case "$os" in
        macos) install_docker_macos ;;
        linux) install_docker_linux ;;
    esac

    if ! docker compose version &>/dev/null; then
        die "docker compose not found. Please install Docker Compose v2."
    fi

    info "Docker is ready ($(docker --version))"
}

# ---------- repo acquisition ----------

in_repo() {
    [[ -f "docker/docker-compose.yml" && -f ".env.example" && -f "CLAUDE.md" ]]
}

ensure_repo() {
    if in_repo; then
        info "Running from repo root"
        return 0
    fi

    info "Not in the Figaro repo -- fetching it..."

    local zip_url="https://github.com/byt3bl33d3r/figaro/archive/refs/heads/main.zip"

    if command -v git &>/dev/null; then
        git clone "$REPO_URL" figaro
    elif command -v curl &>/dev/null; then
        info "git not found, downloading zip with curl..."
        curl -fsSL -o figaro.zip "$zip_url"
        unzip -q figaro.zip
        mv figaro-main figaro
        rm figaro.zip
    elif command -v wget &>/dev/null; then
        info "git not found, downloading zip with wget..."
        wget -q -O figaro.zip "$zip_url"
        unzip -q figaro.zip
        mv figaro-main figaro
        rm figaro.zip
    else
        die "Cannot fetch repo: none of git, curl, or wget are installed."
    fi

    cd figaro
    info "Cloned into $(pwd)"
}

# ---------- overlay selection ----------

validate_overlay() {
    local overlay="$1"
    for valid in $VALID_OVERLAYS; do
        if [[ "$overlay" == "$valid" ]]; then return 0; fi
    done
    die "Invalid overlay '$overlay'. Must be one of: $VALID_OVERLAYS"
}

confirm_prod_overlay() {
    if [[ "$1" != "prod" ]]; then return 0; fi

    warn ""
    warn "WARNING: The 'prod' overlay binds ports to 0.0.0.0, making services"
    warn "accessible from ANY network interface."
    warn ""
    warn "Figaro has NO authentication, NO TLS, and NO authorization."
    warn "Anyone who can reach NATS can control the entire system."
    warn ""

    if ! is_interactive; then
        die "Cannot confirm 'prod' overlay in non-interactive mode. Use 'prod-local' or run interactively."
    fi

    read -rp "Type 'yes' to confirm you understand the risks: " ans
    if [[ "$ans" != "yes" ]]; then
        die "Aborted. Use 'prod-local' for localhost-only deployment."
    fi
}

# ---------- .env setup ----------

setup_env() {
    if [[ -f .env ]]; then
        info ".env file exists"
        return 0
    fi

    info "Creating .env from .env.example..."
    cp .env.example .env

    if ! grep -q "^FIGARO_ENCRYPTION_KEY=" .env; then
        echo "FIGARO_ENCRYPTION_KEY=$(openssl rand -base64 32)" >> .env
    fi

    if is_interactive; then
        if prompt_continue "Open .env in your editor?"; then
            "${EDITOR:-${VISUAL:-nano}}" .env
        fi
    else
        warn "Edit .env before running Figaro (at minimum, review the API keys)."
    fi
}

# ---------- Claude credentials check ----------

check_claude_creds() {
    local missing=0

    if [[ ! -f "$HOME/.claude.json" ]]; then
        warn "$HOME/.claude.json not found"
        missing=1
    fi

    if [[ ! -f "$HOME/.claude/.credentials.json" ]]; then
        warn "$HOME/.claude/.credentials.json not found"
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        warn "Claude credentials are required for workers/supervisors."
        warn "Run 'claude' and sign in to create them."
        warn "On macOS, you can also export credentials with:"
        warn "  security find-generic-password -s \"Claude Code-credentials\" -w > ~/.claude/.credentials.json"

        if is_interactive; then
            prompt_continue "Continue without credentials?" || die "Aborted."
        fi
    else
        info "Claude credentials found"
    fi
}

# ---------- compose helper ----------

run_cmd() {
    printf '\033[0;90m$ %s\033[0m\n' "$*"
    "$@"
}

compose_cmd() {
    run_cmd docker compose \
        -f docker/docker-compose.yml \
        -f "docker/docker-compose.${OVERLAY}.yml" \
        "$@"
}

# ---------- main ----------

cmd_up() {
    local os
    os="$(detect_os)"
    info "Detected OS: $os"

    validate_overlay "$OVERLAY"
    info "Selected overlay: $OVERLAY"

    ensure_docker "$os"
    ensure_repo
    confirm_prod_overlay "$OVERLAY"
    setup_env
    check_claude_creds

    info "Starting Figaro with '$OVERLAY' overlay..."
    compose_cmd up --build -d

    info "Figaro is starting!"
    info "Open http://localhost:8000 once services are ready."
    info ""
    info "Useful commands:"
    info "  ./install.sh down $OVERLAY        # stop services"
    info "  ./install.sh down -v $OVERLAY     # stop and remove all data"
    info "  ./install.sh scale worker=4 $OVERLAY"
}

cmd_build() {
    validate_overlay "$OVERLAY"
    ensure_repo

    info "Building Figaro images (overlay: $OVERLAY)..."
    compose_cmd build
    info "Build complete."
}

cmd_down() {
    validate_overlay "$OVERLAY"
    ensure_repo

    info "Stopping Figaro (overlay: $OVERLAY)..."
    compose_cmd down "${DOWN_ARGS[@]+"${DOWN_ARGS[@]}"}"
    info "Figaro stopped."
}

cmd_scale() {
    validate_overlay "$OVERLAY"
    ensure_repo

    info "Scaling Figaro (overlay: $OVERLAY)..."
    compose_cmd up --build -d "${SCALE_ARGS[@]+"${SCALE_ARGS[@]}"}"
    info "Scaling complete."
}

case "$COMMAND" in
    up)    cmd_up ;;
    build) cmd_build ;;
    down)  cmd_down ;;
    scale) cmd_scale ;;
esac
