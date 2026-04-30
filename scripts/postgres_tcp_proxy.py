from __future__ import annotations

import selectors
import socket
import sys


LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 55432
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 5432


def bridge(client: socket.socket, upstream: socket.socket) -> None:
    selector = selectors.DefaultSelector()
    selector.register(client, selectors.EVENT_READ, upstream)
    selector.register(upstream, selectors.EVENT_READ, client)
    try:
        while True:
            events = selector.select(timeout=60)
            if not events:
                continue
            for key, _ in events:
                source = key.fileobj
                dest = key.data
                chunk = source.recv(65536)
                if not chunk:
                    return
                dest.sendall(chunk)
    finally:
        selector.close()
        try:
            client.close()
        except Exception:
            pass
        try:
            upstream.close()
        except Exception:
            pass


def main() -> int:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LISTEN_HOST, LISTEN_PORT))
    server.listen(64)
    print(f"postgres proxy listening on {LISTEN_HOST}:{LISTEN_PORT} -> {TARGET_HOST}:{TARGET_PORT}", flush=True)
    try:
        while True:
            client, _ = server.accept()
            upstream = socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=15)
            pid = None
            try:
                import threading

                threading.Thread(target=bridge, args=(client, upstream), daemon=True).start()
            except Exception:
                client.close()
                upstream.close()
    except KeyboardInterrupt:
        return 0
    finally:
        server.close()


if __name__ == "__main__":
    sys.exit(main())
