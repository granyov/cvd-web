"""CVD web application package."""

from .app import CVDApplication
from .config import load_config

__all__ = ["CVDApplication", "load_config"]
