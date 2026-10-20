#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

API_URL="http://127.0.0.1:8000"
ADMIN_EMAIL="smoke-admin@example.com"
ADMIN_PASSWORD="smoke-test-password"
EVENT_TYPE="smoke.test"
TIMEOUT_SECONDS=60

finish() {
    local status=$?
    if [ "$status" -ne 0 ]; then
        docker compose logs --no-color --tail=40 || true
    fi
    docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    if [ "$status" -eq 0 ]; then
        echo "PASS: event delivered and signature verified"
    else
        echo "FAIL: smoke test did not complete"
    fi
}

fail() {
    echo "Error: $1" >&2
    exit 1
}

json_field() {
    python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

first_delivery_status() {
    python3 -c 'import json, sys; items = json.load(sys.stdin)["items"]; print(items[0]["status"] if items else "none")'
}

wait_for_ready() {
    local waited=0
    until curl -fsS "$API_URL/health/ready" >/dev/null 2>&1; do
        if [ "$waited" -ge "$TIMEOUT_SECONDS" ]; then
            fail "the API was not ready after $TIMEOUT_SECONDS seconds"
        fi
        sleep 2
        waited=$((waited + 2))
    done
}

wait_for_receiver() {
    local waited=0
    until docker compose logs receiver | grep -q "Demo receiver listening"; do
        if [ "$waited" -ge "$TIMEOUT_SECONDS" ]; then
            fail "the demo receiver did not start"
        fi
        sleep 1
        waited=$((waited + 1))
    done
}

wait_for_delivery() {
    local event_id=$1
    local token=$2
    local waited=0
    local status="none"
    while [ "$waited" -lt "$TIMEOUT_SECONDS" ]; do
        status=$(curl -fsS "$API_URL/api/v1/deliveries?event_id=$event_id" \
            -H "Authorization: Bearer $token" | first_delivery_status)
        if [ "$status" = "succeeded" ]; then
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    fail "the delivery did not succeed within $TIMEOUT_SECONDS seconds (last status: $status)"
}

trap finish EXIT

[ -f .env ] || fail ".env not found; copy .env.example to .env and set HOOKLINE_JWT_SECRET"

echo "Starting the stack"
docker compose up -d --build
wait_for_ready

api_user_id=$(docker compose exec -T api id -u)
[ "$api_user_id" != "0" ] || fail "the api container runs as root"

echo "Creating the admin user"
docker compose exec -T -e HOOKLINE_ADMIN_PASSWORD="$ADMIN_PASSWORD" api \
    python -m hookline.cli create-admin --email "$ADMIN_EMAIL"

token=$(curl -fsS -X POST "$API_URL/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\": \"$ADMIN_EMAIL\", \"password\": \"$ADMIN_PASSWORD\"}" | json_field access_token)

api_key=$(curl -fsS -X POST "$API_URL/api/v1/api-keys" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d '{"name": "smoke test"}' | json_field key)

echo "Creating an endpoint for the demo receiver"
secret=$(curl -fsS -X POST "$API_URL/api/v1/endpoints" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "{\"url\": \"http://receiver:9000/hook\", \"event_types\": [\"$EVENT_TYPE\"]}" | json_field secret)

RECEIVER_SECRET="$secret" docker compose up -d receiver
wait_for_receiver

echo "Sending an event"
event_id=$(curl -fsS -X POST "$API_URL/api/v1/events" \
    -H "X-API-Key: $api_key" \
    -H "Content-Type: application/json" \
    -d "{\"event_type\": \"$EVENT_TYPE\", \"payload\": {\"check\": \"smoke\"}}" | json_field id)

wait_for_delivery "$event_id" "$token"

docker compose logs receiver | grep -q "Verified signature for event $event_id" ||
    fail "the receiver did not verify the signature of event $event_id"
