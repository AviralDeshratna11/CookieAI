"""Ephemeral synthetic local demo. Never loads private .env files or live stores."""

import argparse
import hashlib
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

import uvicorn
from sqlalchemy import insert

from apps.api.main import create_app
from database import tables as t
from database.engine import create_test_schema, make_engine
from memory.autonomy.portal import Portal, SourceInput
from memory.autonomy.service import TaskSupervisor
from memory.config import Settings
from memory.goals.service import GoalInput, GoalService
from memory.schemas import Extraction, RequestContext
from memory.security.auth import Authenticator, Credential
from memory.service import MemoryService
from models.providers import HashEmbedding
from workers.runtime import Worker

DEMO_TOKEN = "cookieai-local-demo-only"


class DemoExtractor:
    def extract(self, context):
        return Extraction()


def build_demo(root):
    # Windows temporary directories can use 8.3 aliases; normalize the trusted
    # operator path before enforcing link-free application workspace paths.
    root = Path(root).resolve()
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///" + (root / "demo.sqlite").as_posix(),
        hermes_workspace=root / "workspace",
        handoff_enabled=True,
        autonomy_enabled=True,
        cloud_disclosure_enabled=False,
        provider_base_url="http://127.0.0.1:1/v1",
    )
    engine = make_engine(settings.database_url)
    create_test_schema(engine)
    ctx = RequestContext(
        user_id=uuid4(),
        requesting_agent_id=uuid4(),
        namespace_id=uuid4(),
        session_id=uuid4(),
        purpose="SYNTHETIC local demonstration",
        requested_scope="write",
    )
    settings.autonomy_allowed_agents = [str(ctx.requesting_agent_id)]
    with engine.begin() as db:
        db.execute(insert(t.users).values(id=ctx.user_id))
        db.execute(
            insert(t.agents).values(id=ctx.requesting_agent_id, user_id=ctx.user_id)
        )
        db.execute(
            insert(t.namespaces).values(
                id=ctx.namespace_id, owner_id=ctx.user_id, kind="USER_PRIVATE"
            )
        )
        db.execute(
            insert(t.grants).values(
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                can_read=True,
                can_write=True,
                can_delete=True,
            )
        )
    memory = MemoryService(engine, HashEmbedding(), DemoExtractor(), settings)
    portal = Portal(memory)
    for title, content in (
        (
            "SYNTHETIC · A · Cedar",
            "Project Cedar prepares a client handoff.\nDecision: Use PostgreSQL.\nDeadline: Review on 30 October 2026.\nQuestion: Who owns launch support?\nNext: Review the handoff with the team.",
        ),
        (
            "SYNTHETIC · B · Beacon",
            "Project Beacon prepares an internal handoff.\nDecision: Use a weekly review.\nNext: Assign an owner.",
        ),
        (
            "SYNTHETIC · C · Restricted",
            "Project C resembles a handoff.\nDecision: Handoff prohibited until approval.\nQuestion: Who can approve this?",
        ),
    ):
        portal.add_source(
            ctx, SourceInput(title=title, content=content, evidence_origin="SYNTHETIC")
        )
    GoalService(memory).create(
        ctx, GoalInput(title="SYNTHETIC · Prepare a project handoff")
    )
    auth = Authenticator(
        [
            Credential(
                hashlib.sha256(DEMO_TOKEN.encode()).hexdigest(),
                ctx.user_id,
                ctx.requesting_agent_id,
                ctx.namespace_id,
            )
        ]
    )
    app = create_app(service=memory, auth=auth)
    app.state.synthetic_demo = True
    return app, memory, ctx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Allow phone testing on trusted local Wi-Fi; synthetic data only",
    )
    args = parser.parse_args()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    with tempfile.TemporaryDirectory(prefix="cookieai-demo-") as temporary:
        app, memory, ctx = build_demo(temporary)
        stop = threading.Event()

        def run_worker():
            worker = Worker(memory, ctx)
            while not stop.wait(1):
                try:
                    TaskSupervisor(memory).tick(ctx)
                    worker.run_once()
                except Exception as error:
                    print("Synthetic demo worker:", type(error).__name__)

        thread = threading.Thread(target=run_worker, daemon=True)
        thread.start()
        print(
            "SYNTHETIC DEMO ONLY · hash-test retrieval, no cloud inference, no claimed learned skills"
        )
        print("Open http://127.0.0.1:8765 · token: " + DEMO_TOKEN)
        if args.lan:
            print(
                "Phone: open http://<PC-IPv4>:8765 on the same trusted Wi-Fi. Synthetic data only; do not port-forward this demo."
            )
        try:
            uvicorn.run(app, host=host, port=8765, log_level="warning")
        finally:
            stop.set()
            thread.join(timeout=10)
            memory.engine.dispose()


if __name__ == "__main__":
    main()
