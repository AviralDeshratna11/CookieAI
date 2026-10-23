"""Derived objects receive an intersection of evidence permissions."""


def evidence_policy(evidence):
    allowed = None
    projects = None
    privacy = {"PUBLIC": 0, "NORMAL": 1, "PRIVATE": 2, "HIGHLY_PRIVATE": 3}
    for memory in evidence:
        if memory.allowed_agent_ids:
            allowed = (
                set(memory.allowed_agent_ids)
                if allowed is None
                else allowed & set(memory.allowed_agent_ids)
            )
        current = set(memory.allowed_project_ids)
        if projects is None:
            projects = current
        elif projects != current:
            raise ValueError(
                "evidence with different project restrictions requires explicit policy reconciliation"
            )
    if allowed is not None and not allowed:
        raise ValueError("evidence has no common agent authorization")
    return dict(
        disclosure="LOCAL_ONLY"
        if any(memory.disclosure == "LOCAL_ONLY" for memory in evidence)
        else "APPROVED_CLOUD",
        allowed_agent_ids=list(allowed or []),
        allowed_project_ids=list(projects or []),
        privacy_class=max(
            (memory.privacy_class for memory in evidence),
            key=privacy.get,
            default="NORMAL",
        ),
    )
