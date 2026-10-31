"""getLinks: return links filtered by type.

Source: links.yaml (loaded at startup, passed in).
"""

from __future__ import annotations

from .schemas import Card, GetLinksArgs, GetLinksResult, LinkInfo


def get_links(
    args: GetLinksArgs,
    *,
    links: list[dict],
) -> GetLinksResult:
    """Return links of the requested type, or a 'not found' with available types."""
    available_types = sorted({link["type"] for link in links})
    type_lower = args.type.lower()

    matched = [link for link in links if link["type"].lower() == type_lower]

    if not matched:
        return GetLinksResult(
            found=False,
            links=[],
            available_types=available_types,
            message=f"No links of type '{args.type}'. Available: {', '.join(available_types)}.",
        )

    return GetLinksResult(
        found=True,
        links=[
            LinkInfo(
                id=link["id"],
                label=link["label"],
                type=link["type"],
                url=link["url"],
                description=link["description"],
            )
            for link in matched
        ],
        available_types=available_types,
    )


def make_card(link_info: LinkInfo) -> Card:
    """Build a card payload from a link result."""
    return Card(
        card_type="link",
        data={
            "id": link_info.id,
            "label": link_info.label,
            "type": link_info.type,
            "url": link_info.url,
            "description": link_info.description,
        },
    )

