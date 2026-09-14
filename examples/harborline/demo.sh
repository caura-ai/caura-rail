#!/usr/bin/env bash
# Harborline Caura Rail demo — install, start, scripted E2E, tear down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BACKEND="${CAURA_BACKEND:-oss}"
if [[ "$BACKEND" != "oss" && "$BACKEND" != "saas" ]]; then
  echo "CAURA_BACKEND must be oss or saas (got: $BACKEND)" >&2
  exit 1
fi

SECRETS_FILE="$ROOT/secrets/${BACKEND}.env"
LLM_FILE="$ROOT/secrets/llm.env"
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Missing $SECRETS_FILE" >&2
  exit 1
fi

API_HOST="${DEMO_API_HOST:-127.0.0.1}"
API_PORT="${DEMO_API_PORT:-8080}"
INTAKE_HOST="${INTAKE_HOST:-127.0.0.1}"
INTAKE_PORT="${INTAKE_PORT:-8787}"
export DEMO_API="http://${API_HOST}:${API_PORT}"
export INTAKE_URL="http://${INTAKE_HOST}:${INTAKE_PORT}"
export CAURA_BACKEND="$BACKEND"
export INTAKE_HOST INTAKE_PORT

# Load Caura + optional LLM secrets into the environment without printing them.
set -a
# shellcheck disable=SC1090
source "$SECRETS_FILE"
if [[ -f "$LLM_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$LLM_FILE"
fi
set +a

# Optional: force offline deterministic replies for the scripted demo.
if [[ "${DEMO_FORCE_DETERMINISTIC:-}" == "1" ]]; then
  export DEMO_FORCE_DETERMINISTIC=1
  unset OPENAI_API_KEY || true
fi

echo "==> Harborline demo (CAURA_BACKEND=$BACKEND)"
echo "==> Installing Python dependencies"
python3 -m venv "$ROOT/.venv"
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -q --upgrade pip
python -m pip install -q -r "$ROOT/requirements.txt"

echo "==> Installing intake (TypeScript) dependencies"
(cd "$ROOT/intake" && npm install --silent)

echo "==> Running unit tests"
python -m pytest "$ROOT/tests" -q

INTAKE_PID=""
API_PID=""
cleanup_procs() {
  if [[ -n "${API_PID}" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
  if [[ -n "${INTAKE_PID}" ]] && kill -0 "$INTAKE_PID" 2>/dev/null; then
    kill "$INTAKE_PID" 2>/dev/null || true
    wait "$INTAKE_PID" 2>/dev/null || true
  fi
}
trap cleanup_procs EXIT

echo "==> Starting TypeScript intake agent on ${INTAKE_HOST}:${INTAKE_PORT}"
(cd "$ROOT/intake" && npm run start) >"$ROOT/.demo-intake.log" 2>&1 &
INTAKE_PID=$!

echo "==> Starting Python API on ${API_HOST}:${API_PORT}"
(
  cd "$ROOT"
  exec python -m uvicorn backend.app:app --host "$API_HOST" --port "$API_PORT" --log-level warning
) >"$ROOT/.demo-api.log" 2>&1 &
API_PID=$!

# Wait for intake health
for _ in $(seq 1 75); do
  if curl -sf "$INTAKE_URL/health" >/dev/null; then
    break
  fi
  if ! kill -0 "$INTAKE_PID" 2>/dev/null; then
    echo "Intake agent exited early. Log:" >&2
    cat "$ROOT/.demo-intake.log" >&2 || true
    exit 1
  fi
  sleep 0.2
done
curl -sf "$INTAKE_URL/health" >/dev/null || {
  echo "Intake agent failed to become healthy" >&2
  cat "$ROOT/.demo-intake.log" >&2 || true
  exit 1
}

echo "==> Running scripted scenario"
python "$ROOT/scripts/run_scenario.py"
echo "==> Demo finished successfully"
