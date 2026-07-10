#!/usr/bin/env python3
from __future__ import annotations

import argparse
import select
import socket
import socketserver
import time


class ForwardHandler(socketserver.BaseRequestHandler):
    target_host: str
    target_port: int
    connect_timeout: float

    def handle(self) -> None:
        upstream = None
        deadline = time.time() + self.connect_timeout
        last_error: OSError | None = None
        while time.time() < deadline:
            try:
                upstream = socket.create_connection(
                    (self.target_host, self.target_port),
                    timeout=1.0,
                )
                break
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        if upstream is None:
            message = f"upstream unavailable: {last_error}\n".encode("utf-8")
            self.request.sendall(message)
            return

        with upstream:
            sockets = [self.request, upstream]
            while True:
                readable, _, exceptional = select.select(sockets, [], sockets, 30)
                if exceptional:
                    return
                if not readable:
                    return
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        return
                    other = upstream if sock is self.request else self.request
                    other.sendall(data)


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal TCP forwarder for OpenClaw secure Docker.")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8788)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    args = parser.parse_args()

    handler = type(
        "ConfiguredForwardHandler",
        (ForwardHandler,),
        {
            "target_host": args.target_host,
            "target_port": args.target_port,
            "connect_timeout": args.connect_timeout,
        },
    )
    with ThreadingTCPServer((args.listen_host, args.listen_port), handler) as server:
        print(
            f"forwarding {args.listen_host}:{args.listen_port} -> "
            f"{args.target_host}:{args.target_port}",
            flush=True,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
