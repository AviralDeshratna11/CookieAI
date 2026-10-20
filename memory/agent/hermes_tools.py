"""Small broker-owned pilot tool set. No shell, network, writes or delegation."""

import ast
import operator
import stat
from decimal import Decimal, localcontext
from pathlib import Path, PureWindowsPath

TOOL_SCHEMAS = [
    {
        "name": "cookieai_calculate",
        "description": "Evaluate bounded decimal arithmetic using + - * / and parentheses. No variables or code.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "maxLength": 200}},
            "required": ["expression"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cookieai_read_text",
        "description": "Read a UTF-8 .txt fixture in this agent's administrator-provisioned workspace. Paths are relative. No other filesystem access.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "maxLength": 200}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = {tool["name"] for tool in TOOL_SCHEMAS}


def calculate(expression):
    if not isinstance(expression, str) or not 1 <= len(expression) <= 200:
        raise ValueError("invalid arithmetic input")
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 60:
        raise ValueError("arithmetic expression too complex")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Decimal(ast.get_source_segment(expression, node))
        elif isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub)
        ):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            value = operations[type(node.op)](visit(node.left), visit(node.right))
        else:
            raise ValueError("unsupported arithmetic syntax")
        if not value.is_finite() or abs(value) > Decimal("1e30"):
            raise ValueError("arithmetic value outside bounds")
        return value

    with localcontext() as context:
        context.prec = 28
        return {"value": str(visit(tree.body))}


def execute_tool(name, arguments, workspace):
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    if name == "cookieai_calculate" and set(arguments) == {"expression"}:
        return calculate(arguments["expression"])
    if name == "cookieai_read_text" and set(arguments) == {"path"}:
        relative = arguments["path"]
        if not isinstance(relative, str) or not 1 <= len(relative) <= 200:
            raise ValueError("invalid relative path")
        path = Path(relative)
        root = Path(workspace).absolute()
        if root.resolve() != root:
            raise PermissionError("workspace must use a physical path without links")
        if (
            path.is_absolute()
            or path.drive
            or ".." in path.parts
            or "\\" in relative
            or ":" in relative
            or PureWindowsPath(relative).is_reserved()
        ):
            raise PermissionError("path outside tool workspace")
        candidate = root / path
        # Reject links/reparse points at each component, not just the final file.
        current = root
        for part in path.parts:
            current = current / part
            info = current.lstat() if current.exists() or current.is_symlink() else None
            if current.is_symlink() or (
                info
                and getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise PermissionError("linked paths are not allowed")
        resolved = candidate.resolve()
        if root not in resolved.parents or resolved.suffix != ".txt":
            raise PermissionError("only workspace text fixtures are allowed")
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise PermissionError("tool workspace inputs must be regular files")
        with resolved.open("rb") as stream:
            content = stream.read(8193)
        if len(content) > 8192:
            raise ValueError("text fixture exceeds byte limit")
        return {"text": content.decode("utf-8")}
    raise PermissionError("tool or arguments outside execution policy")
