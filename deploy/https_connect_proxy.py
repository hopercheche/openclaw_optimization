#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import select
import socket
import socketserver
from urllib.parse import urlparse


def parse_allow_hosts(raw_hosts: str) -> set[str]:
    hosts: set[str] = set()
    for item in raw_hosts.split(","):
        item = item.strip()
        if not item:
            continue
        parsed = urlparse(item if "://" in item else f"https://{item}")
        host = parsed.hostname or item.split("/", 1)[0].split(":", 1)[0]
        if host:
            hosts.add(host.lower())
    return hosts


def parse_connect_target(target: str) -> tuple[str, int]:
    if target.startswith("["):
        host, _, rest = target[1:].partition("]")
        port_text = rest[1:] if rest.startswith(":") else "443"
        return host.lower(), int(port_text)
    host, _, port_text = target.partition(":")
    return host.lower(), int(port_text or "443")


class ConnectProxyHandler(socketserver.BaseRequestHandler):
    allow_hosts: set[str]
    connect_timeout: float

    def handle(self) -> None:
        header = self._read_header()
        if not header:
            return

        first_line = header.splitlines()[0].decode("iso-8859-1", errors="replace")
        parts = first_line.split()
        if len(parts) != 3 or parts[0].upper() != "CONNECT":
            self._send_forbidden("CONNECT required")
            return

        try:
            host, port = parse_connect_target(parts[1])
        except (TypeError, ValueError):
            self._send_forbidden("invalid CONNECT target")
            return

        if host not in self.allow_hosts or port != 443:
            self._send_forbidden("host not allowed")
            return

        try:
            upstream = socket.create_connection((host, port), timeout=self.connect_timeout)
        except OSError:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return

        with upstream:
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._relay(upstream)

    def _read_header(self) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while b"\r\n\r\n" not in b"".join(chunks):
            chunk = self.request.recv(4096)
            if not chunk:
                return b""
            chunks.append(chunk)
            size += len(chunk)
            if size > 65536:
                self._send_forbidden("header too large")
                return b""
        return b"".join(chunks)

    def _relay(self, upstream: socket.socket) -> None:
        sockets = [self.request, upstream]
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional or not readable:
                return
            for sock in readable:
                data = sock.recv(65536)
                if not data:
                    return
                other = upstream if sock is self.request else self.request
                other.sendall(data)

    def _send_forbidden(self, detail: str) -> None:
        body = f"OpenClaw API proxy denied request: {detail}\n".encode("utf-8")
        self.request.sendall(
            b"HTTP/1.1 403 Forbidden\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + body,
        )


class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Allowlist HTTPS CONNECT proxy for OpenClaw.")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8790)
    parser.add_argument(
        "--allow-hosts",
        default=os.environ.get("OPENCLAW_PROXY_ALLOW_HOSTS", ""),
        help="Comma-separated hostnames or HTTPS base URLs.",
    )
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    args = parser.parse_args()

    allow_hosts = parse_allow_hosts(args.allow_hosts)
    if not allow_hosts:
        raise SystemExit("OPENCLAW_PROXY_ALLOW_HOSTS is empty")

    handler = type(
        "ConfiguredConnectProxyHandler",
        (ConnectProxyHandler,),
        {
            "allow_hosts": allow_hosts,
            "connect_timeout": args.connect_timeout,
        },
    )
    with ThreadingTCPServer((args.listen_host, args.listen_port), handler) as server:
        print(
            f"allowing HTTPS CONNECT only to: {', '.join(sorted(allow_hosts))}",
            flush=True,
        )
        server.serve_forever()


if __name__ == "__main__":
    main()
