"""Explicit side-effect registration for migrations and isolated test databases."""

from importlib import import_module


def register_tables():
    for name in (
        "hybrid_tables",
        "learning_tables",
        "experience_tables",
        "graph_tables",
        "procedure_tables",
        "context_tables",
        "reflection_tables",
        "dynamics_tables",
        "operations_tables",
        "source_tables",
        "cognitive_tables",
        "autonomy_tables",
    ):
        import_module("database." + name)
