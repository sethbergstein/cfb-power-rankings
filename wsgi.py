"""WSGI entrypoint for production hosting (Render, etc.)."""

from web.serve import create_app

app = create_app()
