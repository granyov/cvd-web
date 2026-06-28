import socket
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from .app import CVDApplication
from .config import load_config


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(30)
        return connection, address


def main() -> None:
    config = load_config()
    app = CVDApplication(config)
    with make_server(config.host, config.port, app, server_class=ThreadingWSGIServer) as server:
        print(f"CVD web app listening on http://{config.host}:{config.port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("CVD web app stopped.")


if __name__ == "__main__":
    main()
