from __future__ import annotations

from .app import CVDApplication
from .config import load_config


def create_app() -> CVDApplication:
    return CVDApplication(load_config())


application = create_app()
