"""Graph nodes. Each one is a plain function of (state) -> partial state update,
so it can be unit-tested without building the graph.
"""

from deal_rescue.nodes.assemble import assemble, route_after_assemble
from deal_rescue.nodes.fetch_org import fetch_org
from deal_rescue.nodes.fetch_transcript import fetch_transcript
from deal_rescue.nodes.fetch_web import fetch_web
from deal_rescue.nodes.publish import publish
from deal_rescue.nodes.synthesize import build_request, synthesize
from deal_rescue.nodes.validate import route_after_validate, validate

__all__ = [
    "assemble",
    "route_after_assemble",
    "fetch_org",
    "fetch_transcript",
    "fetch_web",
    "publish",
    "build_request",
    "synthesize",
    "route_after_validate",
    "validate",
]
