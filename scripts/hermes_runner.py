"""One-run Hermes host. All model/tool work is brokered through CookieAI stdio.

No application credentials or database connections enter this process. The
version-specific transport/debug overrides are guarded by config/hermes.lock.json.
"""

import contextlib
import json
import logging
import sys
import threading

wire_out = sys.stdout
wire_in = sys.stdin
lock = threading.Lock()


def exchange(payload):
    with lock:
        wire_out.write(json.dumps(payload, separators=(",", ":")) + "\n")
        wire_out.flush()
        reply = json.loads(wire_in.readline())
        if "error" in reply:
            raise RuntimeError("CookieAI broker rejected request")
        return reply["result"]


def main():
    request = json.loads(wire_in.readline())
    sys.path.insert(0, request["source"])
    sys.path.insert(1, request["project"])
    logging.disable(logging.CRITICAL)
    with (
        open(__import__("os").devnull, "w") as sink,
        contextlib.redirect_stdout(sink),
        contextlib.redirect_stderr(sink),
    ):
        import httpx
        from openai import OpenAI
        from run_agent import AIAgent
        from tools.registry import registry
        from toolsets import create_custom_toolset

        from memory.agent.hermes_tools import TOOL_NAMES, TOOL_SCHEMAS

        def transport(http_request):
            payload = json.loads(http_request.content)
            streaming = payload.pop("stream", False)
            payload.pop("stream_options", None)
            response = exchange({"event": "model", "payload": payload})
            if not streaming:
                return httpx.Response(200, json=response)
            # Adapt a bounded complete response to the SDK's SSE transport.
            choices = []
            for choice in response["choices"]:
                delta = dict(choice["message"])
                if delta.get("tool_calls"):
                    delta["tool_calls"] = [
                        {**tool, "index": i}
                        for i, tool in enumerate(delta["tool_calls"])
                    ]
                choices.append(
                    {
                        "index": choice.get("index", 0),
                        "delta": delta,
                        "finish_reason": choice.get("finish_reason", "stop"),
                    }
                )
            chunk = {
                "id": response.get("id", "cookieai"),
                "object": "chat.completion.chunk",
                "created": 0,
                "model": request["model"],
                "choices": choices,
                "usage": response.get("usage"),
            }
            return httpx.Response(
                200,
                content="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n",
                headers={"Content-Type": "text/event-stream"},
            )

        class BrokeredAgent(AIAgent):
            def _create_openai_client(self, client_kwargs, *, reason, shared):
                return OpenAI(
                    api_key="no-provider-credentials",
                    base_url="http://cookieai.invalid/v1",
                    http_client=httpx.Client(transport=httpx.MockTransport(transport)),
                    max_retries=0,
                )

            def _dump_api_request_debug(self, *args, **kwargs):
                # Upstream writes full prompts on some provider errors.
                return None

            def _spawn_background_review(self, *args, **kwargs):
                # CookieAI owns discovery and validated procedure learning.
                return None

            def _save_session_log(self, *args, **kwargs):
                # This release calls the incremental log writer directly after
                # tools, bypassing its persist_session=False entry-point guard.
                return None

        # Schemas originate from the trusted parent, never the model. Handlers
        # remain in the parent; the child gets no service/database credentials.
        extensions = request.get("extension_schemas", [])
        if len(extensions) > 3 or any(
            not schema.get("name", "").startswith("benchmark_") for schema in extensions
        ):
            raise RuntimeError("unsupported extension schema")
        schemas = TOOL_SCHEMAS + extensions
        names = {schema["name"] for schema in schemas}
        if len(names) != len(schemas):
            raise RuntimeError("duplicate tool schema")
        allowed = set(request.get("allowed_tools", TOOL_NAMES))
        if not allowed or not allowed.issubset(names):
            raise RuntimeError("unsupported tool policy")
        for schema in schemas:
            if schema["name"] not in allowed:
                continue

            def handler(arguments, _name=schema["name"], **kwargs):
                return json.dumps(
                    exchange({"event": "tool", "name": _name, "arguments": arguments})
                )

            registry.register(schema["name"], "cookieai_pilot", schema, handler)
        create_custom_toolset(
            "cookieai_pilot",
            "CookieAI broker-controlled pilot tools",
            tools=sorted(allowed),
        )
        agent = BrokeredAgent(
            base_url="http://127.0.0.1:1/v1",
            api_key="no-provider-credentials",
            provider="custom",
            api_mode="chat_completions",
            model=request["model"],
            session_id=request["run_id"],
            enabled_toolsets=["cookieai_pilot"],
            max_iterations=request["max_iterations"],
            max_tokens=request["output_tokens"],
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            session_db=None,
            persist_session=False,
            save_trajectories=False,
            checkpoints_enabled=False,
            fallback_model=None,
        )
        actual = {tool["function"]["name"] for tool in agent.tools}
        if actual != allowed:
            raise RuntimeError("Hermes tool policy mismatch")
        agent.compression_enabled = False
        result = agent.run_conversation(
            request["message"],
            system_message=request["system"],
            conversation_history=[],
            task_id=request["run_id"],
        )
    wire_out.write(
        json.dumps(
            {
                "event": "result",
                "answer": result.get("final_response", ""),
                "completed": result.get("completed", False),
            }
        )
        + "\n"
    )
    wire_out.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never leak a prompt, token, path, tool output or provider error body.
        wire_out.write('{"event":"failed"}\n')
        wire_out.flush()
        sys.exit(1)
