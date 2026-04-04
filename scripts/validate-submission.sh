#!/usr/bin/env bash
#
# validate-submission.sh — OpenEnv Submission Validator
#
# Checks that your HF Space is live, Docker builds, openenv validate passes,
# and inference.py emits the required [START]/[STEP]/[END] logs.

set -uo pipefail

DOCKER_BUILD_TIMEOUT=600
INFERENCE_TIMEOUT=180

if [ -t 1 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BOLD='\033[1m'
  NC='\033[0m'
else
  RED='' GREEN='' YELLOW='' BOLD='' NC=''
fi

run_with_timeout() {
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@"
  else
    "$@" &
    local pid=$!
    ( sleep "$secs" && kill "$pid" 2>/dev/null ) &
    local watcher=$!
    wait "$pid" 2>/dev/null
    local rc=$?
    kill "$watcher" 2>/dev/null || true
    wait "$watcher" 2>/dev/null || true
    return "$rc"
  fi
}

portable_mktemp() {
  local prefix="${1:-validate}"
  mktemp "${TMPDIR:-/tmp}/${prefix}-XXXXXX" 2>/dev/null || mktemp
}

CLEANUP_FILES=()
cleanup() { rm -f "${CLEANUP_FILES[@]+"${CLEANUP_FILES[@]}"}"; }
trap cleanup EXIT

PING_URL="${1:-}"
REPO_DIR="${2:-.}"

if [ -z "$PING_URL" ]; then
  printf "Usage: %s <ping_url> [repo_dir]\n" "$0"
  printf "\n"
  printf "  ping_url   Your HuggingFace Space URL (e.g. https://your-space.hf.space)\n"
  printf "  repo_dir   Path to your repo (default: current directory)\n"
  exit 1
fi

if ! REPO_DIR="$(cd "$REPO_DIR" 2>/dev/null && pwd)"; then
  printf "Error: directory '%s' not found\n" "${2:-.}"
  exit 1
fi

PING_URL="${PING_URL%/}"
PASS=0

log()  { printf "[%s] %b\n" "$(date -u +%H:%M:%S)" "$*"; }
pass() { log "${GREEN}PASSED${NC} -- $1"; PASS=$((PASS + 1)); }
fail() { log "${RED}FAILED${NC} -- $1"; }
hint() { printf "  ${YELLOW}Hint:${NC} %b\n" "$1"; }
stop_at() {
  printf "\n"
  printf "${RED}${BOLD}Validation stopped at %s.${NC} Fix the above before continuing.\n" "$1"
  exit 1
}

find_python() {
  if command -v python >/dev/null 2>&1; then
    printf "python"
  elif command -v python3 >/dev/null 2>&1; then
    printf "python3"
  else
    return 1
  fi
}

printf "\n"
printf "${BOLD}========================================${NC}\n"
printf "${BOLD}  OpenEnv Submission Validator${NC}\n"
printf "${BOLD}========================================${NC}\n"
log "Repo:     $REPO_DIR"
log "Ping URL: $PING_URL"
printf "\n"

log "${BOLD}Step 1/4: Pinging HF Space${NC} ($PING_URL/reset) ..."

CURL_OUTPUT=$(portable_mktemp "validate-curl")
CLEANUP_FILES+=("$CURL_OUTPUT")
HTTP_CODE=$(curl -s -o "$CURL_OUTPUT" -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" -d '{}' \
  "$PING_URL/reset" --max-time 30 2>"$CURL_OUTPUT" || printf "000")

if [ "$HTTP_CODE" = "200" ]; then
  pass "HF Space is live and responds to /reset"
elif [ "$HTTP_CODE" = "000" ]; then
  fail "HF Space not reachable (connection failed or timed out)"
  hint "Check your network connection and that the Space is running."
  hint "Try: curl -s -o /dev/null -w '%%{http_code}' -X POST $PING_URL/reset"
  stop_at "Step 1"
else
  fail "HF Space /reset returned HTTP $HTTP_CODE (expected 200)"
  hint "Make sure your Space is running and the URL is correct."
  hint "Try opening $PING_URL in your browser first."
  stop_at "Step 1"
fi

log "${BOLD}Step 2/4: Running docker build${NC} ..."

if ! command -v docker >/dev/null 2>&1; then
  fail "docker command not found"
  hint "Install Docker: https://docs.docker.com/get-docker/"
  stop_at "Step 2"
fi

if [ ! -f "$REPO_DIR/Dockerfile" ]; then
  fail "No Dockerfile found in repo root"
  stop_at "Step 2"
fi

BUILD_OK=false
BUILD_OUTPUT=$(run_with_timeout "$DOCKER_BUILD_TIMEOUT" docker build "$REPO_DIR" 2>&1) && BUILD_OK=true

if [ "$BUILD_OK" = true ]; then
  pass "Docker build succeeded"
else
  fail "Docker build failed (timeout=${DOCKER_BUILD_TIMEOUT}s)"
  printf "%s\n" "$BUILD_OUTPUT" | tail -20
  stop_at "Step 2"
fi

log "${BOLD}Step 3/4: Running openenv validate${NC} ..."

if ! command -v openenv >/dev/null 2>&1; then
  fail "openenv command not found"
  hint "Install it: pip install openenv-core"
  stop_at "Step 3"
fi

VALIDATE_OK=false
VALIDATE_OUTPUT=$(cd "$REPO_DIR" && openenv validate 2>&1) && VALIDATE_OK=true

if [ "$VALIDATE_OK" = true ]; then
  pass "openenv validate passed"
  [ -n "$VALIDATE_OUTPUT" ] && log "  $VALIDATE_OUTPUT"
else
  fail "openenv validate failed"
  printf "%s\n" "$VALIDATE_OUTPUT"
  stop_at "Step 3"
fi

log "${BOLD}Step 4/4: Verifying inference stdout format${NC} ..."

PYTHON_BIN=$(find_python) || {
  fail "python command not found"
  hint "Install Python and ensure python or python3 is on PATH."
  stop_at "Step 4"
}

if [ ! -f "$REPO_DIR/inference.py" ]; then
  fail "inference.py not found in repo root"
  stop_at "Step 4"
fi

INFERENCE_LOG=$(portable_mktemp "validate-inference")
CLEANUP_FILES+=("$INFERENCE_LOG")

INFERENCE_OK=false
INFERENCE_OUTPUT=$(cd "$REPO_DIR" && run_with_timeout "$INFERENCE_TIMEOUT" "$PYTHON_BIN" inference.py --offline 2>&1) && INFERENCE_OK=true
printf "%s\n" "$INFERENCE_OUTPUT" > "$INFERENCE_LOG"

if [ "$INFERENCE_OK" != true ]; then
  fail "python inference.py --offline failed or timed out"
  printf "%s\n" "$INFERENCE_OUTPUT"
  stop_at "Step 4"
fi

START_COUNT=$(grep -c '^\[START\] task=' "$INFERENCE_LOG" || true)
STEP_COUNT=$(grep -c '^\[STEP\] step=' "$INFERENCE_LOG" || true)
END_COUNT=$(grep -c '^\[END\] success=' "$INFERENCE_LOG" || true)

if [ "$START_COUNT" -lt 3 ] || [ "$STEP_COUNT" -lt 3 ] || [ "$END_COUNT" -lt 3 ]; then
  fail "inference.py did not emit the expected structured logs for all tasks"
  hint "Expected at least 3 [START], 3 [STEP], and 3 [END] lines from the offline benchmark run."
  printf "%s\n" "$INFERENCE_OUTPUT"
  stop_at "Step 4"
fi

pass "inference.py emits structured [START]/[STEP]/[END] logs"

printf "\n"
printf "${BOLD}========================================${NC}\n"
printf "${GREEN}${BOLD}  All 4/4 checks passed!${NC}\n"
printf "${GREEN}${BOLD}  Your submission is ready for pre-submit review.${NC}\n"
printf "${BOLD}========================================${NC}\n"
printf "\n"

exit 0
