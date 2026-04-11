"""Evaluator package.

Avoid importing provider modules at package import time to prevent circular
dependencies during factory auto-registration.
"""
