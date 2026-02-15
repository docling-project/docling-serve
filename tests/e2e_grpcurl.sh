#!/usr/bin/env bash
# End-to-end test: start a real gRPC server, then test with grpcurl.
# Requires: grpcurl, uv, and a test PDF at tests/2206.01062v1.pdf
# Usage: ./tests/e2e_grpcurl.sh [port]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${1:-50099}"
TEST_PDF="$SCRIPT_DIR/2206.01062v1.pdf"
FAILURES=0

cleanup() {
    if [[ -n "${SERVER_PID:-}" ]]; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    rm -f "$TMPFILE"
}
trap cleanup EXIT

fail() {
    echo "FAIL: $1"
    FAILURES=$((FAILURES + 1))
}

pass() {
    echo "PASS: $1"
}

# --- Start server ---
echo "=== Starting gRPC server on port $PORT ==="
uv run docling-serve-grpc run --port "$PORT" > /tmp/e2e_grpc_server.log 2>&1 &
SERVER_PID=$!

for i in $(seq 1 120); do
    if grpcurl -plaintext "localhost:$PORT" list >/dev/null 2>&1; then
        echo "Server ready after ${i}s"
        break
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "FATAL: server process died. Logs:"
        cat /tmp/e2e_grpc_server.log
        exit 1
    fi
    if [[ $i -eq 120 ]]; then
        echo "FATAL: server did not become ready within 120s"
        exit 1
    fi
    sleep 1
done

echo ""

# --- Test 1: Service reflection ---
echo "=== 1. List services (reflection) ==="
SERVICES=$(grpcurl -plaintext "localhost:$PORT" list 2>&1)
echo "$SERVICES"
if echo "$SERVICES" | grep -q "ai.docling.serve.v1.DoclingServeService"; then
    pass "DoclingServeService listed via reflection"
else
    fail "DoclingServeService not found in reflection"
fi
echo ""

# --- Test 2: Describe service ---
echo "=== 2. Describe DoclingServeService ==="
DESC=$(grpcurl -plaintext "localhost:$PORT" describe ai.docling.serve.v1.DoclingServeService 2>&1)
echo "$DESC"
for rpc in Health ConvertSource ConvertSourceStream WatchConvertSource; do
    if echo "$DESC" | grep -q "$rpc"; then
        pass "RPC $rpc found in service description"
    else
        fail "RPC $rpc missing from service description"
    fi
done
echo ""

# --- Test 3: Health check ---
echo "=== 3. Health check ==="
HEALTH=$(grpcurl -plaintext "localhost:$PORT" ai.docling.serve.v1.DoclingServeService/Health 2>&1)
echo "$HEALTH"
if echo "$HEALTH" | grep -q '"status"'; then
    pass "Health check returned status"
else
    fail "Health check missing status"
fi
echo ""

# --- Test 4: ConvertSource with a real PDF ---
echo "=== 4. ConvertSource with real PDF ==="
if [[ ! -f "$TEST_PDF" ]]; then
    echo "SKIP: test PDF not found at $TEST_PDF"
else
    TMPFILE=$(mktemp /tmp/grpc_e2e_request.XXXXXX.json)
    python3 -c "
import base64, json, sys
with open(sys.argv[1], 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
req = {'request': {'sources': [{'file': {'base64_string': b64, 'filename': 'test.pdf'}}]}}
with open(sys.argv[2], 'w') as f:
    json.dump(req, f)
" "$TEST_PDF" "$TMPFILE"
    RESULT=$(grpcurl -plaintext -d @ "localhost:$PORT" ai.docling.serve.v1.DoclingServeService/ConvertSource < "$TMPFILE" 2>&1)
    if echo "$RESULT" | grep -q '"schema_name"'; then
        pass "ConvertSource returned DoclingDocument with schema_name"
    else
        fail "ConvertSource did not return expected DoclingDocument"
        echo "$RESULT" | head -20
    fi
    if echo "$RESULT" | grep -q '"texts"'; then
        pass "ConvertSource response contains texts"
    else
        fail "ConvertSource response missing texts"
    fi
    if echo "$RESULT" | grep -q '"tables"'; then
        pass "ConvertSource response contains tables"
    else
        fail "ConvertSource response missing tables (may be expected for some PDFs)"
    fi
    RESP_SIZE=$(echo "$RESULT" | wc -c)
    echo "Response size: $RESP_SIZE bytes"
fi
echo ""

# --- Test 5: ConvertSourceStream (server-side streaming) ---
echo "=== 5. ConvertSourceStream with real PDF ==="
if [[ -f "${TMPFILE:-}" ]]; then
    STREAM_RESULT=$(grpcurl -plaintext -d @ "localhost:$PORT" ai.docling.serve.v1.DoclingServeService/ConvertSourceStream < "$TMPFILE" 2>&1)
    if echo "$STREAM_RESULT" | grep -q '"schema_name"'; then
        pass "ConvertSourceStream returned DoclingDocument"
    else
        fail "ConvertSourceStream did not return expected DoclingDocument"
        echo "$STREAM_RESULT" | head -20
    fi
else
    echo "SKIP: no test PDF"
fi
echo ""

# --- Test 6: Empty source (expect INVALID_ARGUMENT) ---
echo "=== 6. ConvertSource with empty source (expect error) ==="
ERR_RESULT=$(grpcurl -plaintext -d '{
  "request": {
    "sources": [{}]
  }
}' "localhost:$PORT" ai.docling.serve.v1.DoclingServeService/ConvertSource 2>&1 || true)
echo "$ERR_RESULT"
if echo "$ERR_RESULT" | grep -qi "InvalidArgument\|INVALID_ARGUMENT\|no variant"; then
    pass "Empty source correctly rejected with INVALID_ARGUMENT"
else
    fail "Empty source not rejected as expected"
fi
echo ""

# --- Test 7: No sources (expect INVALID_ARGUMENT) ---
echo "=== 7. ConvertSource with no sources (expect error) ==="
ERR_RESULT2=$(grpcurl -plaintext -d '{
  "request": {
    "sources": []
  }
}' "localhost:$PORT" ai.docling.serve.v1.DoclingServeService/ConvertSource 2>&1 || true)
echo "$ERR_RESULT2"
if echo "$ERR_RESULT2" | grep -qi "InvalidArgument\|INVALID_ARGUMENT\|at least one"; then
    pass "No sources correctly rejected with INVALID_ARGUMENT"
else
    fail "No sources not rejected as expected"
fi
echo ""

# --- Test 8: ConvertSource with JSON export format ---
echo "=== 8. ConvertSource with JSON export format ==="
if [[ -f "${TMPFILE:-}" ]]; then
    # Add options to the existing request using jq
    TMPFILE_JSON=$(mktemp /tmp/grpc_e2e_json.XXXXXX.json)
    jq '.request.options = {"to_formats": ["OUTPUT_FORMAT_JSON"]}' "$TMPFILE" > "$TMPFILE_JSON"
    JSON_RESULT=$(grpcurl -plaintext -d @ "localhost:$PORT" ai.docling.serve.v1.DoclingServeService/ConvertSource < "$TMPFILE_JSON" 2>&1)
    rm -f "$TMPFILE_JSON"
    if echo "$JSON_RESULT" | grep -q '"json"'; then
        pass "JSON export returned json content"
    else
        fail "JSON export did not return json content"
        echo "$JSON_RESULT" | head -20
    fi
else
    echo "SKIP: no test PDF"
fi
echo ""

# --- Summary ---
echo "================================="
if [[ $FAILURES -eq 0 ]]; then
    echo "All e2e grpcurl tests PASSED"
    exit 0
else
    echo "$FAILURES test(s) FAILED"
    exit 1
fi
