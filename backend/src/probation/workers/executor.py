"""Executor worker: Sole execution boundary holding write credentials and executing side-effects.

Authority: docs/CONTRACT.md section 3, section 8, and invariant I-2.
CRITICAL: Only the Executor performs side-effects and holds write credentials.
"""
