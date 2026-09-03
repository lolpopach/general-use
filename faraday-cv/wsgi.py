"""WSGI entrypoint for a hosted deployment.

    gunicorn wsgi:app

Local settings apply unless overridden: FARADAYCV_LOCAL_MODE defaults to on,
so a public deployment must set it to 0 (render.yaml and fly.toml already
do). See faradaycv/webapp.py:create_app for what that controls.
"""

from faradaycv.webapp import create_app

app = create_app()
