"""
Test Configuration
~~~~~~~~~~~~~~~~~~
Shared fixtures and test database setup.
"""

import os

# MUST be set before importing any app modules
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-minimum-64-chars-abcdefghijklmnopq")
os.environ.setdefault("DB_ENCRYPTION_KEY", "")
