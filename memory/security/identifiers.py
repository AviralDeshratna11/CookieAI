"""Opaque operational keys keep caller-provided text out of retained metadata."""

import hashlib


def opaque(value):
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def job_key(namespace, value):
    return f"{namespace}:{opaque(value)}"
