"""Paper Discovery Subsystem for Research Aid."""

from paper_discovery.models import (
    SearchScope,
    TraversalDirection,
    AcademicPaperRecommendation,
    PaperDiscoveryResult,
    LiteratureSynthesis,
    CitationGraphResult,
)
from paper_discovery.discovery import (
    PaperDiscoveryEngine,
    discover_similar_papers,
    synthesize_literature_context,
    traverse_citation_network,
)

__all__ = [
    "SearchScope",
    "TraversalDirection",
    "AcademicPaperRecommendation",
    "PaperDiscoveryResult",
    "LiteratureSynthesis",
    "CitationGraphResult",
    "PaperDiscoveryEngine",
    "discover_similar_papers",
    "synthesize_literature_context",
    "traverse_citation_network",
]
