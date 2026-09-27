"""Check upload deadlines against an isolated, loopback-bound production Caddy."""
import argparse
import http.client
import socket
import time
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="http://127.0.0.1:<isolated Caddy port>")
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port:
        parser.error("Use an isolated HTTP proxy bound to 127.0.0.1.")
    path = "/api/v1/projects/missing/sources/upload"
    began = time.monotonic()
    with socket.create_connection((url.hostname, url.port), timeout=65) as sock:
        sock.sendall((f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                      "Content-Length: 100\r\nConnection: close\r\n\r\n{").encode())
        try:
            # Caddy may send an empty response on cancellation. Require the connection
            # to close, rather than treating a response header as released capacity.
            while sock.recv(4096):
                pass
        except ConnectionResetError:
            pass
        except TimeoutError:
            raise SystemExit("FAIL: an incomplete upload still holds a connection after 65 seconds.")
    elapsed = time.monotonic() - began
    assert 55 <= elapsed < 65, f"Expected the 60-second body deadline; received {elapsed:.1f}s."
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=10)
    try:
        connection.request("POST", path, body=b"x" * 1024 * 1024,
                           headers={"Content-Type": "application/octet-stream"})
        response = connection.getresponse()
        assert response.status in {401, 403}, response.status  # Session/Origin guards, after body intake.
        response.read()
        connection.request("GET", "/api/v1/health")
        response = connection.getresponse()
        assert response.status == 200, response.status
        response.read()
    finally:
        connection.close()
    print(f"PASS: stalled body closed at {elapsed:.1f}s; complete 1 MiB body reached security checks; health 200.")


if __name__ == "__main__":
    main()
