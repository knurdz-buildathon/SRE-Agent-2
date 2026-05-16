from http.server import HTTPServer, BaseHTTPRequestHandler
import json


class HealthyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "healthy", "uptime": 100}).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            html = """<!DOCTYPE html>
<html><head><title>Healthy App</title></head>
<body><div id="app"><h1>Healthy App Running</h1><p>All systems operational.</p></div></body>
</html>"""
            self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), HealthyHandler)
    print("Healthy app running on port 8080")
    server.serve_forever()
