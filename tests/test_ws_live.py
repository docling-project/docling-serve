#!/usr/bin/env python3
"""Test WebSocket conversion against live ACA endpoint."""

import asyncio
import hashlib
import json
import math
import os
import sys

import ssl

import websockets  # pip install websockets

ENDPOINT = os.getenv("DOCLING_SERVE_CONVERT_WS",
                     "wss://HOST/v1/convert/ws")
CHUNK_SIZE = 1_048_576  # 1 MB

# Force HTTP/1.1 — ACA defaults to h2 which doesn't support WebSocket upgrade
SSL_CTX = ssl.create_default_context()
SSL_CTX.set_alpn_protocols(["http/1.1"])


async def test_connect():
    """Test basic connectivity — connect and receive greeting."""
    print("=== Test: Connect ===")
    async with websockets.connect(ENDPOINT, ssl=SSL_CTX, ping_interval=None) as ws:
        msg = json.loads(await ws.recv())
        print(f"  Connected: {msg}")
        assert msg["type"] == "connected", f"Expected 'connected', got {msg['type']}"
        print("  ✓ Connected successfully\n")


async def test_upload_convert(file_path: str, output_path: str | None = None):
    """Upload a file and receive the conversion result."""
    print(f"=== Test: Upload + Convert ({file_path}) ===")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    filename = file_path.split("/")[-1]
    total_bytes = len(file_bytes)
    num_chunks = math.ceil(total_bytes / CHUNK_SIZE)
    sha = hashlib.sha256(file_bytes).hexdigest()

    async with websockets.connect(ENDPOINT, ssl=SSL_CTX, ping_interval=None, max_size=100_000_000) as ws:
        # 1. Receive connected greeting
        msg = json.loads(await ws.recv())
        print(f"  Connected: queue_length={msg.get('queue_length')}")

        # 2. Send upload_start
        await ws.send(json.dumps({
            "type": "upload_start",
            "filename": filename,
            "total_bytes": total_bytes,
            "content_type": "application/pdf",
            "chunks": num_chunks,
            "options": {"to_formats": ["md", "json"]},
        }))
        print(f"  Uploading {filename} ({total_bytes} bytes, {num_chunks} chunks)...")

        # 3. Send binary chunks
        for i in range(num_chunks):
            start = i * CHUNK_SIZE
            end = min(start + CHUNK_SIZE, total_bytes)
            await ws.send(file_bytes[start:end])
            print(f"    Chunk {i+1}/{num_chunks} sent")

        # 4. Send upload_end
        await ws.send(json.dumps({"type": "upload_end", "sha256": sha}))
        print(f"  Upload complete (sha256={sha[:12]}...)")

        # 5. Receive status updates, heartbeats, and result.
        #    Stream result chunks to a file (if --output given) so we
        #    never hold the full payload in memory.
        result_meta = None
        result_file = None
        hasher = hashlib.sha256()
        chunks_received = 0

        try:
            while True:
                raw = await ws.recv()

                if isinstance(raw, str):
                    msg = json.loads(raw)
                    msg_type = msg["type"]

                    if msg_type == "status":
                        print(f"  Status: {msg.get('task_status')} "
                              f"position={msg.get('task_position')} "
                              f"progress={msg.get('progress')}")
                    elif msg_type == "heartbeat":
                        pos = msg.get('task_position')
                        pos_str = "Running" if pos is None else f"position={pos}"
                        elapsed = msg.get('elapsed')
                        elapsed_str = f" elapsed={elapsed:.1f}s" if elapsed else ""
                        print(f"  Heartbeat: {pos_str}{elapsed_str}")
                    elif msg_type == "result_start":
                        result_meta = msg
                        print(f"  Result starting: {msg['total_bytes']} bytes, "
                              f"{msg['content_type']}, {msg['chunks']} chunks")
                        if output_path:
                            result_file = open(output_path, "wb")
                    elif msg_type == "result_end":
                        print(f"  Result end: sha256={msg['sha256'][:12]}...")
                        actual_sha = hasher.hexdigest()
                        assert actual_sha == msg["sha256"], \
                            f"SHA mismatch: {actual_sha} != {msg['sha256']}"
                        print(f"  ✓ SHA-256 verified")
                        if output_path:
                            print(f"  ✓ Result written to {output_path}")
                        break
                    elif msg_type == "error":
                        print(f"  ✗ Error: {msg['error']}")
                        return
                else:
                    # Binary chunk — stream to file or accumulate
                    hasher.update(raw)
                    chunks_received += 1
                    if result_file:
                        result_file.write(raw)
                    print(f"    Result chunk {chunks_received} received "
                          f"({len(raw)} bytes)")
        finally:
            if result_file:
                result_file.close()

    print("  ✓ Conversion complete!\n")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test WebSocket conversion against live ACA endpoint.")
    parser.add_argument("file", nargs="?", help="PDF file to upload and convert")
    parser.add_argument("-o", "--output", help="Write result to this file instead of discarding")
    args = parser.parse_args()

    await test_connect()

    if args.file:
        await test_upload_convert(args.file, output_path=args.output)
    else:
        print("Tip: pass a PDF path to test file upload conversion:")
        print(f"  python {sys.argv[0]} tests/2206.01062v1.pdf")
        print(f"  python {sys.argv[0]} tests/2206.01062v1.pdf -o result.json")


if __name__ == "__main__":
    asyncio.run(main())
