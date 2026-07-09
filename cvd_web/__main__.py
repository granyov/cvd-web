import argparse
import socket
import sys
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from .app import CVDApplication
from .config import load_config
from .migrations import migration_status, run_migrations, status_as_json


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def get_request(self) -> tuple[socket.socket, tuple[str, int]]:
        connection, address = super().get_request()
        connection.settimeout(30)
        return connection, address

    def handle_error(self, request, client_address) -> None:
        if isinstance(sys.exc_info()[1], TimeoutError):
            return
        super().handle_error(request, client_address)


def migrate_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m cvd_web migrate")
    parser.add_argument("--check", action="store_true", help="Only report pending migrations.")
    parser.add_argument("--no-backup", action="store_true", help="Apply migrations without pre-migration backup.")
    parser.add_argument("--backup-dir", help="Directory for pre-migration SQLite backups.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    config = load_config()
    if args.check:
        status = migration_status(config.db_path)
        if args.json:
            print(status_as_json(status))
        else:
            print(f"Database: {status['db_path']}")
            print(f"Applied: {len(status['applied'])}")
            print(f"Pending: {', '.join(status['pending']) or 'none'}")
        return 1 if status["pending"] else 0

    result = run_migrations(
        config,
        backup=not args.no_backup,
        backup_dir=Path(args.backup_dir) if args.backup_dir else None,
    )
    if args.json:
        print(status_as_json(result))
    else:
        print(f"Database: {result['after']['db_path']}")
        if result["backup_path"]:
            print(f"Backup: {result['backup_path']}")
        print(f"Applied: {len(result['after']['applied'])}")
        print(f"Pending: {', '.join(result['after']['pending']) or 'none'}")
    return 0 if result["ok"] else 1


def serve_main() -> int:
    config = load_config()
    app = CVDApplication(config)
    with make_server(config.host, config.port, app, server_class=ThreadingWSGIServer) as server:
        print(f"CVD web app listening on http://{config.host}:{config.port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("CVD web app stopped.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "migrate":
        return migrate_main(argv[1:])
    return serve_main()


if __name__ == "__main__":
    raise SystemExit(main())
