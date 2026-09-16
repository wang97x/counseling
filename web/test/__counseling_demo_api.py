import json
from http.server import BaseHTTPRequestHandler, HTTPServer

USER = {"id": 7, "username": "演示辅导员", "uid": "demo", "role": "user", "business_roles": ["counselor", "business_admin"], "department_id": 1, "department_name": "演示心理中心"}

class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_json(USER if self.path.startswith("/api/auth/me") else [])

    def do_POST(self):
        self.send_json({})

    def log_message(self, *_):
        pass

HTTPServer(("127.0.0.1", 5051), Handler).serve_forever()
