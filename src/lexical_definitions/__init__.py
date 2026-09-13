"""Lexical Definitions Subsystem for Research Aid."""

from lexical_definitions.models import WordSense, WordDefinitionResult
from lexical_definitions.definitions import (
    LexicalDefinitionsEngine,
    lookup_contextual_definition,
    harvest_dictionary_senses,
    disambiguate_active_sense,
)

__all__ = [
    "WordSense",
    "WordDefinitionResult",
    "LexicalDefinitionsEngine",
    "lookup_contextual_definition",
    "harvest_dictionary_senses",
    "disambiguate_active_sense",
]
