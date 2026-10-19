"""Versioned prompt resources shipped with the package."""

from importlib.resources import files


def load(name):
    return files(__package__).joinpath(name + ".txt").read_text(encoding="utf-8")
