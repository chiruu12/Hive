"""Hive REST API server (optional ``[api]`` extra).

Importing this package requires FastAPI/uvicorn. The CLI guards the import and
raises a clear ``MissingDependencyError('api')`` when the extra is not installed,
so core never imports FastAPI.
"""

from hive.server.app import create_app

__all__ = ["create_app"]
