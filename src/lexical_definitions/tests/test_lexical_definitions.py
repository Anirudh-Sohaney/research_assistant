"""Unit tests for lexical_definitions subsystem."""

import os
import sys
from unittest.mock import patch

import pytest

_src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from api_gateway.models import ApiResponse
from lexical_definitions.models import WordDefinitionResult, WordSense
from lexical_definitions.definitions import (
    LexicalDefinitionsEngine,
    lookup_contextual_definition,
    harvest_dictionary_senses,
    disambiguate_active_sense,
)


class TestModels:
    def test_word_sense_creation(self):
        sense = WordSense(
            definition="A method of proof",
            part_of_speech="noun",
            examples=["Proof by induction"],
            confidence=0.85,
        )
        assert sense.definition == "A method of proof"
        assert sense.confidence == 0.85


@pytest.mark.asyncio
class TestHarvesting:
    @patch("lexical_definitions.definitions.dispatch_api_request")
    async def test_harvest_from_freedictionary(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=200,
            data=[
                {
                    "word": "induction",
                    "phonetic": "/ɪnˈdʌkʃən/",
                    "phonetics": [{"text": "/ɪnˈdʌkʃən/", "audio": "http://audio.mp3"}],
                    "meanings": [
                        {
                            "partOfSpeech": "noun",
                            "definitions": [
                                {"definition": "Act of inducting.", "example": "initiation"},
                                {"definition": "Mathematical proof technique.", "example": "proof"},
                            ],
                        }
                    ],
                }
            ],
            latency_ms=15.0,
        )
        engine = LexicalDefinitionsEngine()
        ipa, audio, senses = await engine.harvest_dictionary_senses("induction")
        assert ipa == "/ɪnˈdʌkʃən/"
        assert audio == "http://audio.mp3"
        assert len(senses) == 2

    @patch("lexical_definitions.definitions.dispatch_api_request")
    async def test_offline_fallback(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=500,
            data=None,
            latency_ms=5.0,
            error="API down",
        )
        engine = LexicalDefinitionsEngine()
        ipa, audio, senses = await engine.harvest_dictionary_senses("induction")
        assert len(senses) >= 2
        assert any("mathematical" in s.definition.lower() for s in senses)


class TestDisambiguation:
    def test_mathematical_induction_polysemy(self):
        engine = LexicalDefinitionsEngine()
        candidate_senses = [
            WordSense(definition="Ceremonial initiation into an organization", part_of_speech="noun"),
            WordSense(definition="Mathematical proof method for theorems over natural numbers", part_of_speech="noun"),
            WordSense(definition="Electromagnetic physical phenomenon", part_of_speech="noun"),
        ]
        sentence = "The paper utilizes mathematical induction to prove theorem 4."
        ranked = engine.disambiguate_active_sense(candidate_senses, "induction", sentence)

        assert len(ranked) == 3
        # Mathematical sense must rank #1
        assert "mathematical" in ranked[0].definition.lower()
        assert ranked[0].confidence > ranked[1].confidence

    def test_biological_culture_polysemy(self):
        engine = LexicalDefinitionsEngine()
        candidate_senses = [
            WordSense(definition="Societal customs, beliefs, and arts", part_of_speech="noun"),
            WordSense(definition="Cultivation of bacteria in artificial growth medium", part_of_speech="noun"),
        ]
        sentence = "The bacterial culture was incubated at 37°C."
        ranked = engine.disambiguate_active_sense(candidate_senses, "culture", sentence)

        assert len(ranked) == 2
        # Biological sense must rank #1
        assert "bacteria" in ranked[0].definition.lower()


@pytest.mark.asyncio
class TestFullPipeline:
    @patch("lexical_definitions.definitions.dispatch_api_request")
    async def test_lookup_contextual_definition(self, mock_dispatch):
        mock_dispatch.return_value = ApiResponse(
            status_code=500,
            data=None,
            latency_ms=5.0,
            error="API down",
        )
        # Using offline fallback for mathematical induction
        result = await lookup_contextual_definition(
            target_word="induction",
            sentence_context="We prove this property by mathematical induction on n.",
        )
        assert isinstance(result, WordDefinitionResult)
        assert result.word == "induction"
        assert result.primary_sense is not None
        assert "mathematical" in result.primary_sense.definition.lower()
        assert result.disambiguation_confidence > 0.5
