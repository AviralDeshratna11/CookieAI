"""Content-free, transactionally charged daily execution budgets."""

from functools import wraps

from sqlalchemy import insert, select, update

from database import autonomy_tables as a
from memory.schemas import utcnow


class BudgetExceeded(Exception):
    pass


def charge(db, ctx, settings, event_id, kind):
    # Caller holds the existing namespace advisory lock. Charges survive memory
    # deletion so deleting a task cannot reset the day's execution allowance.
    if db.execute(
        select(a.charges.c.event_id).where(
            a.charges.c.namespace_id == ctx.namespace_id,
            a.charges.c.event_id == event_id,
        )
    ).first():
        return
    day = utcnow().date().isoformat()
    scope = (
        a.usage.c.namespace_id == ctx.namespace_id,
        a.usage.c.agent_id == ctx.requesting_agent_id,
        a.usage.c.day == day,
    )
    usage = db.execute(select(a.usage).where(*scope)).mappings().first()
    count = usage[kind] if usage else 0
    maximum = getattr(settings, "autonomy_daily_" + kind)
    if count >= maximum:
        raise BudgetExceeded("Daily execution allowance exhausted")
    if not usage:
        db.execute(
            insert(a.usage).values(
                namespace_id=ctx.namespace_id,
                agent_id=ctx.requesting_agent_id,
                day=day,
                tool_calls=int(kind == "tool_calls"),
                model_calls=int(kind == "model_calls"),
            )
        )
    else:
        db.execute(update(a.usage).where(*scope).values({kind: count + 1}))
    db.execute(
        insert(a.charges).values(
            namespace_id=ctx.namespace_id,
            event_id=event_id,
            agent_id=ctx.requesting_agent_id,
            day=day,
            kind=kind,
        )
    )


def stop_on_budget(function):
    @wraps(function)
    def run(self, ctx, identity):
        try:
            return function(self, ctx, identity)
        except BudgetExceeded:
            return self._stop_for_budget(ctx, identity)

    return run
