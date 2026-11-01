"""getLinks: links of one type from links.yaml, one link card each.

The allowed types are read from links.yaml, so the argument model is built at
startup: pydantic then rejects an unknown type, and the generated schema shows
the model the exact list (as a JSON-schema enum).
"""

from typing import Literal

from pydantic import Field, create_model

from .kb_data import KbData
from .schemas import Args


def links_args_model(kb: KbData) -> type[Args]:
    labels: dict[str, list[str]] = {}
    for link in kb.links:
        labels.setdefault(link.type, []).append(link.label)
    described = "; ".join(f"{t} ({', '.join(names)})" for t, names in labels.items())
    return create_model(
        "GetLinksArgs",
        __base__=Args,
        type=(Literal[tuple(labels)], Field(description=f"Link type. One of: {described}.")),
    )


def get_links(args: Args, kb: KbData) -> tuple[dict, list[dict]]:
    matched = [link for link in kb.links if link.type == args.type]
    result = {"links": [{"label": link.label, "url": link.url, "description": link.description} for link in matched]}
    cards = [
        {"card_id": f"link:{link.id}", "type": "link", "data": {"label": link.label, "url": link.url, "description": link.description}}
        for link in matched
    ]
    return result, cards
