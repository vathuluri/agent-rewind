import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .demo import start_demo, fork_demo

WEB = Path(__file__).parent / "web"


def handler_for(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, value, status=200):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                return self.send({"error": "Loopback host required"}, 403)
            url = urlparse(self.path)
            try:
                if url.path == "/api/runs":
                    return self.send(store.runs())
                if url.path.startswith("/api/run/"):
                    return self.send(store.get(url.path.removeprefix("/api/run/")))
                if url.path == "/api/compare":
                    args = parse_qs(url.query)
                    return self.send(store.compare(args["left"][0], args["right"][0]))
                files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
                if url.path not in files:
                    return self.send({"error": "Not found"}, 404)
                name, mime = files[url.path]
                self.send_response(200)
                self.send_header("Content-Type", mime + "; charset=utf-8")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write((WEB / name).read_bytes())
            except (KeyError, IndexError):
                self.send({"error": "Run or comparison target not found"}, 404)
            except ValueError as error:
                self.send({"error": str(error)}, 400)

        def do_POST(self):
            # Reject cross-site browser writes and DNS-rebinding hostnames.
            allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get("Host") not in allowed_hosts:
                return self.send({"error": "Loopback host required"}, 403)
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed_hosts}:
                return self.send({"error": "Cross-origin writes refused"}, 403)
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send({"error": "JSON required"}, 415)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16000:
                    return self.send({"error": "Invalid request size"}, 413)
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Request must be an object")
                if self.path == "/api/demo":
                    run_id = start_demo(store, data.get("policy", "speed-first"))
                elif self.path == "/api/fork":
                    run_id = fork_demo(store, data["run_id"], data["seq"], data["policy"])
                else:
                    return self.send({"error": "Not found"}, 404)
                self.send({"id": run_id}, 201)
            except (ValueError, KeyError, TypeError) as error:
                self.send({"error": str(error)}, 400)
    return Handler


def serve(store, port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(store))
    print(f"Agent Rewind: http://127.0.0.1:{server.server_port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
