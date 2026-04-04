"""
PythonAnywhere WSGI entry point.

In PythonAnywhere's Web tab, set:
  Source code: /home/<username>/quinta-da-baronesa
  Working directory: /home/<username>/quinta-da-baronesa
  WSGI file: this file (wsgi.py)

Replace the import below if your virtualenv path differs.
"""
import sys
import os

# Add project root to path
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from a2wsgi import ASGIMiddleware
from app.main import app

# PythonAnywhere looks for 'application'
application = ASGIMiddleware(app)
