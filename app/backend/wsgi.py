#!/usr/bin/env python3
"""
WSGI wrapper for Flask app (alternative to CGI)
"""
import sys
import os

sys.path.insert(0, os.path.expanduser("~") + "/python_libs")

from app import app

if __name__ == "__main__":
    app.run()
