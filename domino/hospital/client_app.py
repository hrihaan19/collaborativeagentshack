"""Flower ClientApp = the hospital agent. Runs on the hospital's SuperNode.

Hospital identity comes from the SuperNode --node-config ("hospital-id"),
never from the payload. The hospital exposes no inbound port: this code only
ever runs when the SuperNode pulls a message from the SuperLink.
"""
from __future__ import annotations

import logging
from pathlib import Path

from flwr.app import ConfigRecord, Context, Message, RecordDict
from flwr.clientapp import ClientApp

from domino.hospital import logic
from domino.hospital.store import HospitalStore, default_state_dir
from domino.protocol import (
    PAYLOAD_KEY,
    RECORD_KEY,
    CoordinatorRequest,
    HospitalEgress,
    MessageType,
    dumps,
    parse_request,
)

log = logging.getLogger("domino.hospital")
app = ClientApp()


def _store(context: Context) -> HospitalStore:
    hid = str(context.node_config.get("hospital-id", "")).upper()
    if hid not in ("A", "B", "C"):
        raise RuntimeError("SuperNode started without --node-config hospital-id=\"A|B|C\"")
    sd = context.node_config.get("state-dir")
    state_dir = Path(str(sd)) if sd else default_state_dir(hid)
    store = HospitalStore(hid, state_dir)
    store.seed()  # no-op if already seeded
    return store


def _reply(msg: Message, egress: HospitalEgress) -> Message:
    rec = ConfigRecord({PAYLOAD_KEY: dumps(egress)})
    return Message(content=RecordDict({RECORD_KEY: rec}), reply_to=msg)


@app.query()
def domino_query(msg: Message, context: Context) -> Message:
    store = _store(context)
    md = msg.metadata
    try:
        raw = msg.content[RECORD_KEY][PAYLOAD_KEY]
        req: CoordinatorRequest = parse_request(bytes(raw))  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - never leak exception text
        store.log("REQUEST_REJECTED", {"flower_message_id": md.message_id, "code": "SCHEMA_INVALID"})
        e = HospitalEgress(run_id=str(md.run_id), round_id=str(md.group_id), message_type=MessageType.REFUSAL,
                           hospital_id=store.hospital_id, refusal_code="SCHEMA_INVALID")
        return _reply(msg, e)

    store.log("FLOWER_MESSAGE_IN", {
        "message_type": req.message_type.value, "domino_message_id": req.message_id,
        "flower_run_id": md.run_id, "flower_message_id": md.message_id,
        "src_node_id": md.src_node_id, "dst_node_id": md.dst_node_id, "node_id": context.node_id,
    })
    egress = logic.handle(store, req)
    store.log("FLOWER_MESSAGE_OUT", {"message_type": egress.message_type.value, "domino_message_id": egress.message_id,
                                     "vertices": [v.vertex_token for v in egress.vertices]})
    return _reply(msg, egress)
