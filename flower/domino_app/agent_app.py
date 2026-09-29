"""Domino AgentApp (flwr>=1.39). The same app runs in two places:

* on SuperGrid (coordinator): agent.grid.tools() offers get_nodes / push_messages / pull_messages
* on a hospital SuperNode:    agent.grid.tools() offers only push_reply_message

Role is detected from that tool set. Nothing else differs.
"""
from __future__ import annotations

import json
import uuid

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context

app = AgentApp()


def grid(agent: AgentSession, name: str, **args):
    out = agent.grid.call({"type": "function_call", "name": name,
                           "call_id": "call_" + uuid.uuid4().hex[:8], "arguments": json.dumps(args)})
    raw = out.get("output", "{}") if isinstance(out, dict) else "{}"
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {"raw": raw}


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    from domino_app import coordinator, hospital

    names = {t.get("name") for t in agent.grid.tools()}
    if "get_nodes" in names:
        coordinator.run(agent, context)
    else:
        hospital.run(agent, context)
