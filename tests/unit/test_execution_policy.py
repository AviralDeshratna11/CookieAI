from uuid import uuid4

import pytest

from memory.agent.hermes import HermesBackend
from memory.agent.hermes_tools import execute_tool
from memory.config import Settings
from memory.context.budget import ContextBudgetExceeded, TokenCounter, check_prompt
from memory.security.auth import AccessDenied


def test_pilot_tools_reject_code_escape_and_oversize_files(tmp_path):
    assert execute_tool(
        "cookieai_calculate", {"expression": "(0.1 + 0.2) * 10"}, tmp_path
    ) == {"value": "3.0"}
    for expression in [
        "__import__('os').getcwd()",
        "2 ** 1000000",
        "True",
        "1e99",
        "[1]*1000",
    ]:
        with pytest.raises((ValueError, SyntaxError)):
            execute_tool("cookieai_calculate", {"expression": expression}, tmp_path)
    for path in [
        "../outside.txt",
        "C:\\outside.txt",
        "/outside.txt",
        ".env",
        "data.json",
    ]:
        with pytest.raises(PermissionError):
            execute_tool("cookieai_read_text", {"path": path}, tmp_path)
    (tmp_path / "fixture.txt").write_text("approved fixture", encoding="utf-8")
    assert (
        execute_tool("cookieai_read_text", {"path": "fixture.txt"}, tmp_path)["text"]
        == "approved fixture"
    )
    (tmp_path / "large.txt").write_bytes(b"x" * 8193)
    with pytest.raises(ValueError):
        execute_tool("cookieai_read_text", {"path": "large.txt"}, tmp_path)
    with pytest.raises(PermissionError):
        execute_tool("terminal", {"command": "echo forbidden"}, tmp_path)


def test_hermes_requires_separate_agent_opt_in_and_rejects_nonretention(ctx):
    settings = Settings(_env_file=None)
    with pytest.raises(AccessDenied):
        HermesBackend.authorize(settings, ctx, True)
    settings.hermes_enabled = True
    settings.hermes_allowed_agents = [str(uuid4())]
    with pytest.raises(AccessDenied):
        HermesBackend.authorize(settings, ctx, True)
    settings.hermes_allowed_agents = [str(ctx.requesting_agent_id)]
    with pytest.raises(ValueError, match="retain:false"):
        HermesBackend.authorize(settings, ctx, False)


def test_full_prompt_includes_tools_output_and_template_reserve():
    messages = [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "request"},
    ]
    result = check_prompt(messages, TokenCounter(), 1000, 200, 128)
    assert result["total_reserved_tokens"] <= 1000
    assert result["counter"] == "conservative_utf8_upper_bound"
    with pytest.raises(ContextBudgetExceeded):
        check_prompt(messages, TokenCounter(), 1000, 200, 128, [{"schema": "x" * 1000}])
