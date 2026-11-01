"""Synthetic incident workflow. No production systems or LLMs are contacted."""
import copy

POLICIES = {"speed-first", "evidence-first"}


def start_demo(store, policy="speed-first"):
    if policy not in POLICIES:
        raise ValueError("Unknown demo policy")
    run_id = store.create("Checkout latency alert", policy)
    state = {"phase": "inspect", "alert": "checkout latency", "service": "checkout",
             "restart_allowed": False, "deployment_healthy": True, "outcome": "pending",
             "tool_calls": 0, "scenario": "checkout-v1"}
    store.append(run_id, "start", "Incident received", state,
                 inputs={"environment": "synthetic demo"})
    resume_demo(store, run_id, policy)
    return run_id


def resume_demo(store, run_id, policy):
    if policy not in POLICIES:
        raise ValueError("Unknown demo policy")
    run = store.get(run_id)
    if not run["events"]:
        raise ValueError("Demo needs an existing checkpoint")
    state = copy.deepcopy(run["events"][-1]["state"])
    if state.get("scenario") != "checkout-v1":
        raise ValueError("Only the checkout-v1 synthetic scenario can be resumed by the demo runner")
    if state["phase"] == "inspect":
        state.update(phase="decide", tool_calls=state["tool_calls"] + 1,
                     observation="Alert window is stale; current latency is normal.")
        store.append(run_id, "observation", "Inspect current service health", state,
                     output={"p95_ms": 118, "threshold_ms": 500, "alert_age_minutes": 24})
    if state["phase"] == "decide":
        action = "restart" if policy == "speed-first" else "close-stale-alert"
        state.update(phase="execute", action=action)
        store.append(run_id, "decision", f"Policy selected: {action}", state,
                     inputs={"policy": policy}, output={"action": action})
    if state["phase"] == "execute":
        state["tool_calls"] += 1
        if state["action"] == "restart":
            state.update(phase="done", outcome="blocked", reason="Restart is outside the agent's permitted actions.")
            store.append(run_id, "tool", "Restart rejected by permission boundary", state,
                         output={"allowed": False, "side_effect": False})
        else:
            state.update(phase="done", outcome="resolved", reason="Current health verified; stale alert closed in simulation.")
            store.append(run_id, "tool", "Close stale alert", state,
                         output={"closed": True, "side_effect": "synthetic record only"})
        store.append(run_id, "finish", "Workflow finished", state)


def fork_demo(store, run_id, seq, policy):
    # Validate before creating the branch so a bad request leaves no orphan run.
    state = store.checkpoint(run_id, seq)
    if policy not in POLICIES or state.get("scenario") != "checkout-v1" or state.get("phase") not in {"inspect", "decide"}:
        raise ValueError("Fork this demo at Incident received or Inspect current service health, before the decision")
    child = store.fork(run_id, seq, policy)
    resume_demo(store, child, policy)
    return child
