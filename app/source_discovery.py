"""Propose reviewed ATS source definitions from stored application URLs."""

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.models import Listing

TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,99}$", re.I)
ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "boards.eu.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.eu.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
}


@dataclass(frozen=True)
class SourceProposal:
    key: str
    employer: str
    kind: str
    tenant: str
    discovered_from_listing_id: int
    discovered_from_url: str
    source_names: tuple[str, ...]
    reason: str


def nested_urls(url: str) -> tuple[str, ...]:
    """Return the outer URL and HTTP(S) URLs encoded in its query values."""
    pending = [url]
    seen: set[str] = set()
    found: list[str] = []
    while pending and len(seen) < 10:
        candidate = unquote(pending.pop(0)).strip()
        if candidate in seen or not candidate.startswith(("http://", "https://")):
            continue
        seen.add(candidate)
        found.append(candidate)
        for _, value in parse_qsl(urlsplit(candidate).query, keep_blank_values=False):
            decoded = unquote(value).strip()
            if decoded.startswith(("http://", "https://")):
                pending.append(decoded)
    return tuple(found)


def recognize_ats_url(url: str) -> tuple[str, str, str] | None:
    for candidate in nested_urls(url):
        parts = urlsplit(candidate)
        host = (parts.hostname or "").lower()
        kind = ATS_HOSTS.get(host)
        if not kind:
            continue
        path_parts = [part for part in parts.path.split("/") if part]
        tenant = path_parts[0] if path_parts else ""
        if kind == "greenhouse" and (not tenant or tenant == "embed"):
            tenant = dict(parse_qsl(parts.query)).get("for", "")
        tenant = tenant.lower()
        if not TENANT_RE.fullmatch(tenant):
            continue
        reason = (
            f"recognized {kind} tenant in application URL"
            if candidate == url
            else f"recognized {kind} tenant in encoded redirect target"
        )
        return kind, tenant, reason
    return None


def discover_source_proposals(session: Session) -> list[SourceProposal]:
    listings = session.scalars(
        select(Listing)
        .options(selectinload(Listing.sources))
        .order_by(Listing.application_url, Listing.id)
    ).all()
    proposals: dict[tuple[str, str], SourceProposal] = {}
    source_names: dict[tuple[str, str], set[str]] = {}
    for listing in listings:
        match = recognize_ats_url(listing.application_url)
        if match is None:
            continue
        kind, tenant, reason = match
        identity = (kind, tenant)
        source_names.setdefault(identity, set()).update(
            source.source_name for source in listing.sources
        )
        if identity not in proposals:
            proposals[identity] = SourceProposal(
                key=f"{kind}:{tenant}",
                employer=listing.company,
                kind=kind,
                tenant=tenant,
                discovered_from_listing_id=listing.id,
                discovered_from_url=listing.application_url,
                source_names=(),
                reason=reason,
            )
    return [
        SourceProposal(
            **{
                **asdict(proposal),
                "source_names": tuple(sorted(source_names[identity])),
            },
        )
        for identity, proposal in sorted(proposals.items())
    ]


def proposals_json(proposals: list[SourceProposal]) -> str:
    return json.dumps(
        [asdict(proposal) for proposal in proposals],
        indent=2,
        sort_keys=True,
    ) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Propose direct ATS sources from stored application URLs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Explicitly write the reviewed proposal JSON to this path.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow --output to replace an existing file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with SessionLocal() as session:
        output = proposals_json(discover_source_proposals(session))
    if args.output is None:
        print(output, end="")
        return
    if args.output.exists() and not args.force:
        raise SystemExit(f"Refusing to replace existing file: {args.output}")
    args.output.write_text(output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
