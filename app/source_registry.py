"""Reviewed source definitions enabled for scheduled ingestion."""

from app.source_types import SourceSpec


CURATED_SOURCES = (
    SourceSpec(
        key="markdown:speedyapply-2027-swe",
        name="SpeedyApply 2027 SWE",
        kind="markdown",
        public_url=(
            "https://github.com/speedyapply/2027-SWE-College-Jobs/"
            "blob/main/NEW_GRAD_USA.md"
        ),
        parameters={
            "raw_url": (
                "https://raw.githubusercontent.com/speedyapply/"
                "2027-SWE-College-Jobs/main/NEW_GRAD_USA.md"
            ),
        },
    ),
    SourceSpec(
        key="markdown:vansh-new-grad-2027",
        name="Vansh New Grad 2027",
        kind="markdown",
        public_url="https://github.com/vanshb03/New-Grad-2027",
        parameters={
            "raw_url": (
                "https://raw.githubusercontent.com/vanshb03/"
                "New-Grad-2027/main/README.md"
            ),
        },
    ),
)

DIRECT_SOURCES = (
    # Initial reviewed pilot, validated against public board endpoints before
    # scheduled activation.
    SourceSpec(
        key="greenhouse:figma",
        name="Figma Careers",
        kind="greenhouse",
        public_url="https://boards.greenhouse.io/figma",
        parameters={"tenant": "figma", "employer": "Figma"},
        enabled=True,
    ),
    SourceSpec(
        key="lever:palantir",
        name="Palantir Careers",
        kind="lever",
        public_url="https://jobs.lever.co/palantir",
        parameters={"tenant": "palantir", "employer": "Palantir"},
        enabled=True,
    ),
    SourceSpec(
        key="ashby:ramp",
        name="Ramp Careers",
        kind="ashby",
        public_url="https://jobs.ashbyhq.com/ramp",
        parameters={"tenant": "ramp", "employer": "Ramp"},
        enabled=True,
    ),
)
SOURCE_REGISTRY = CURATED_SOURCES + DIRECT_SOURCES
