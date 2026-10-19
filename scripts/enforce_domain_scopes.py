"""One-time, idempotent source refactor for operation-bound permission decorators."""

import ast
from pathlib import Path

TARGETS = {
    "memory/episodes/service.py": {
        "EpisodeService": {
            "record": "write",
            "segment": "write",
            "get": "read",
            "search": "read",
        }
    },
    "memory/experiences/service.py": {
        "ExperienceService": {"compile": "write", "get": "read", "search": "read"}
    },
    "memory/procedures/service.py": {
        "ProcedureService": {
            "compile": "write",
            "feedback": "write",
            "get": "read",
            "search": "read",
        }
    },
    "memory/graph/service.py": {"GraphService": {"connect": "write", "recall": "read"}},
    "memory/goals/service.py": {
        "GoalService": {"create": "write", "patch": "write", "list": "read"}
    },
    "memory/context/transfer.py": {
        "ContextTransferService": {"build": "read", "transfer": "read"}
    },
    "memory/reflection/engine.py": {
        "ReflectionEngine": {"run": "write", "list": "read"}
    },
    "memory/serendipity/engine.py": {"SerendipityEngine": {"run": "write"}},
    "memory/decay/service.py": {
        "DynamicsService": {"decay": "write", "pin": "write", "cluster": "write"}
    },
    "memory/goals/prospective.py": {
        "ProspectiveService": {
            "create": "write",
            "activate": "write",
            "open_loop": "write",
        }
    },
}

for filename, classes in TARGETS.items():
    path = Path(filename)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    insertions = []
    found = set()
    for definition in tree.body:
        if not isinstance(definition, ast.ClassDef) or definition.name not in classes:
            continue
        for method in definition.body:
            if (
                isinstance(method, ast.FunctionDef)
                and method.name in classes[definition.name]
            ):
                found.add((definition.name, method.name))
                if not any(
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "require_scope"
                    for decorator in method.decorator_list
                ):
                    scope = classes[definition.name][method.name]
                    insertions.append(
                        (method.lineno - 1, f'    @require_scope("{scope}")\n')
                    )
    expected = {
        (class_name, method)
        for class_name, methods in classes.items()
        for method in methods
    }
    if found != expected:
        raise RuntimeError(f"missing methods in {filename}: {expected - found}")
    for index, text in sorted(insertions, reverse=True):
        lines.insert(index, text)
    revised = "".join(lines)
    if "from memory.security.auth import require_scope\n" not in revised:
        revised = "from memory.security.auth import require_scope\n" + revised
    path.write_text(revised, encoding="utf-8")
