"""Build the exchange graph from sanitized hospital egress."""
from __future__ import annotations

from domino.protocol import HospitalEgress, ScreenResult


def build_graph(responses: list[HospitalEgress]) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    vertices: dict[str, dict] = {}
    donor_vertex: dict[str, str] = {}
    for e in responses:
        for v in e.vertices:
            vertices[v.vertex_token] = {
                "kind": v.kind,
                "availability": v.availability.value,
                "hospital_id": e.hospital_id,  # identity from the node, not the vertex payload
                "record_version": v.record_version,
            }
        for d in e.donors:
            donor_vertex[d.donor_token] = d.vertex_token
    edges: set[tuple[str, str]] = set()
    for e in responses:
        for ev in e.evaluations:
            if ev.result != ScreenResult.TOY_CANDIDATE:
                continue
            u = donor_vertex.get(ev.donor_token)
            if u is None or ev.recipient_vertex not in vertices or u == ev.recipient_vertex:
                continue
            # only the hospital that owns the recipient may assert an edge into it
            if vertices[ev.recipient_vertex]["hospital_id"] != e.hospital_id:
                continue
            edges.add((u, ev.recipient_vertex))
    return vertices, sorted(edges)
