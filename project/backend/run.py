#!/usr/bin/env python3
"""
CGI wrapper para Flask na HostGator
Roda a aplicação Flask como CGI
"""
import sys
import os

# Add python_libs to path
sys.path.insert(0, os.path.expanduser("~") + "/python_libs")
sys.path.insert(0, os.path.dirname(__file__))

# Fix SSL para HostGator
os.environ['SSL_CERT_FILE'] = os.path.expanduser("~") + "/python_libs/certifi/cacert.pem"
os.environ['REQUESTS_CA_BUNDLE'] = os.path.expanduser("~") + "/python_libs/certifi/cacert.pem"

from wsgiref.handlers import CGIHandler
from app import app

if __name__ == '__main__':
    CGIHandler().run(app)
