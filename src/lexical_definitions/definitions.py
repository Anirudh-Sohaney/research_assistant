"""Lexical Definitions Engine with multi-source harvesting and contextual Word Sense Disambiguation."""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from api_gateway.models import ExternalService, RequestPayload
from api_gateway.gateway import dispatch_api_request
from lexical_definitions.models import WordDefinitionResult, WordSense

log = logging.getLogger("lexical_definitions")

# Built-in offline dictionary for common polysemous academic terms
OFFLINE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "induction": {
        "phonetic": "/ɪnˈdʌk.ʃən/",
        "senses": [
            {
                "pos": "noun",
                "definition": "A method of mathematical proof typically used to establish a given statement for all natural numbers.",
                "examples": ["The paper utilizes mathematical induction to prove theorem 4."],
                "keywords": {"math", "mathematical", "theorem", "proof", "prove", "logic", "deduction", "axiom"},
            },
            {
                "pos": "noun",
                "definition": "The production of an electromotive force across an electrical conductor in a changing magnetic field.",
                "examples": ["Faraday discovered electromagnetic induction."],
                "keywords": {"magnetic", "field", "electromagnetic", "electricity", "coil", "voltage", "current"},
            },
            {
                "pos": "noun",
                "definition": "The formal act or process of introducing someone to a new job, position, or organization.",
                "examples": ["The university held an induction ceremony for new faculty."],
                "keywords": {"ceremony", "organization", "job", "membership", "initiation", "hall", "fame"},
            },
        ],
    },
    "culture": {
        "phonetic": "/ˈkʌl.tʃər/",
        "senses": [
            {
                "pos": "noun",
                "definition": "A biological cultivation of bacteria, tissue cells, or microorganisms in an artificial growth medium.",
                "examples": ["The bacterial culture was incubated at 37°C."],
                "keywords": {"bacteria", "bacterial", "incubated", "cell", "tissue", "organism", "medium", "petri", "temperature", "specimen"},
            },
            {
                "pos": "noun",
                "definition": "The collective customs, social institutions, beliefs, and artistic achievements of a human society or group.",
                "examples": ["Anthropologists examine how corporate culture affects communication."],
                "keywords": {"society", "social", "anthropology", "art", "customs", "human", "tradition", "behavior"},
            },
        ],
    },
    "model": {
        "phonetic": "/ˈmɒd.əl/",
        "senses": [
            {
                "pos": "noun",
                "definition": "A simplified mathematical, statistical, or computational description of a system or process to assist calculations.",
                "examples": ["The transformer model optimizes predictive cross-entropy."],
                "keywords": {"computational", "machine", "learning", "neural", "parameter", "transformer", "statistical", "algorithm"},
            },
            {
                "pos": "noun",
                "definition": "A three-dimensional representation or miniature replica of a person, structure, or object.",
                "examples": ["The architect built an acrylic scale model of the cathedral."],
                "keywords": {"scale", "replica", "physical", "clay", "miniature", "architecture", "sculpture"},
            },
        ],
    },
}


class LexicalDefinitionsEngine:
    """Discovers dictionary definitions and performs contextual Word Sense Disambiguation."""

    async def harvest_dictionary_senses(
        self, word: str
    ) -> Tuple[str, Optional[str], List[WordSense]]:
        """Harvests senses, phonetic IPA, and audio from FreeDictionary or offline fallback."""
        clean_word = word.strip().lower()
        senses: List[WordSense] = []
        phonetic_ipa = ""
        audio_url = None

        # 1. Query FreeDictionary API via API Gateway
        try:
            resp = await dispatch_api_request(
                service=ExternalService.FREEDICTIONARY,
                endpoint=f"/{clean_word}",
                payload=RequestPayload(),
            )
            if resp.is_success and isinstance(resp.data, list) and len(resp.data) > 0:
                entry = resp.data[0]
                phonetic_ipa = entry.get("phonetic", "")
                for ph in entry.get("phonetics", []):
                    if not phonetic_ipa and ph.get("text"):
                        phonetic_ipa = ph.get("text")
                    if ph.get("audio"):
                        audio_url = ph.get("audio")

                for meaning in entry.get("meanings", []):
                    pos = meaning.get("partOfSpeech", "general")
                    for d in meaning.get("definitions", []):
                        definition_text = d.get("definition", "").strip()
                        example_list = [d["example"]] if "example" in d and d["example"] else []
                        synonym_list = d.get("synonyms", [])
                        if definition_text:
                            senses.append(
                                WordSense(
                                    definition=definition_text,
                                    part_of_speech=pos,
                                    examples=example_list,
                                    synonyms=synonym_list,
                                )
                            )
        except Exception as exc:
            log.warning("FreeDictionary API query error: %s", exc)

        # 2. Offline fallback if online senses are empty or for common academic polysemy
        if not senses and clean_word in OFFLINE_DEFINITIONS:
            offline = OFFLINE_DEFINITIONS[clean_word]
            phonetic_ipa = offline.get("phonetic", "")
            for s in offline.get("senses", []):
                senses.append(
                    WordSense(
                        definition=s["definition"],
                        part_of_speech=s["pos"],
                        examples=s.get("examples", []),
                    )
                )

        return phonetic_ipa, audio_url, senses

    @staticmethod
    def _stem(word: str) -> str:
        w = word.lower()
        for suffix in ("ical", "ial", "ian", "ic", "ing", "tion", "ion", "ed", "es", "s", "al", "ia", "a", "um", "us"):
            if w.endswith(suffix) and len(w) > len(suffix) + 2:
                w = w[: -len(suffix)]
                break
        return w[:5] if len(w) >= 5 else w

    def disambiguate_active_sense(
        self, candidate_senses: List[WordSense], target_word: str, sentence: str
    ) -> List[WordSense]:
        """Scores and re-orders senses using contextual token overlap and semantic agreement."""
        if not candidate_senses:
            return []

        clean_target = target_word.strip().lower()
        sentence_raw_tokens = set(re.findall(r"\b[a-z]{3,}\b", sentence.lower()))
        sentence_raw_tokens.discard(clean_target)
        sentence_stems = {self._stem(t) for t in sentence_raw_tokens}

        scored_senses: List[Tuple[float, WordSense]] = []

        for i, sense in enumerate(candidate_senses):
            text_to_match = (
                sense.definition.lower()
                + " "
                + " ".join(sense.examples).lower()
                + " "
                + " ".join(sense.synonyms).lower()
            )
            def_raw_tokens = set(re.findall(r"\b[a-z]{3,}\b", text_to_match))
            def_stems = {self._stem(t) for t in def_raw_tokens}

            # Count direct stem matches between sentence and definition
            stem_overlap = sentence_stems.intersection(def_stems)
            raw_overlap = sentence_raw_tokens.intersection(def_raw_tokens)

            # Weight overlap heavily
            score = 0.10 + (0.45 * len(raw_overlap)) + (0.35 * len(stem_overlap))

            # Small tie-breaker preferring earlier dictionary senses
            score += 0.01 * (len(candidate_senses) - i)

            sense.confidence = round(min(0.99, max(0.10, score)), 3)
            scored_senses.append((sense.confidence, sense))

        # Sort descending by confidence
        scored_senses.sort(key=lambda pair: pair[0], reverse=True)
        return [pair[1] for pair in scored_senses]

    async def lookup_contextual_definition(
        self, target_word: str, sentence_context: str
    ) -> WordDefinitionResult:
        """Complete 2-stage zero-token contextual definition pipeline."""
        clean_word = target_word.strip().lower()
        ipa, audio, senses = await self.harvest_dictionary_senses(clean_word)

        if not senses:
            return WordDefinitionResult(
                word=target_word,
                phonetic_ipa=ipa,
                audio_url=audio,
                primary_sense=WordSense(
                    definition=f"No definition found for '{target_word}'.",
                    part_of_speech="unknown",
                ),
            )

        ranked_senses = self.disambiguate_active_sense(senses, clean_word, sentence_context)
        primary = ranked_senses[0] if ranked_senses else None
        secondary = ranked_senses[1:] if len(ranked_senses) > 1 else []
        conf = primary.confidence if primary else 0.0

        return WordDefinitionResult(
            word=target_word,
            phonetic_ipa=ipa,
            audio_url=audio,
            primary_sense=primary,
            secondary_senses=secondary,
            disambiguation_confidence=conf,
            etymology="",
        )


_global_definitions_engine = LexicalDefinitionsEngine()


async def lookup_contextual_definition(
    target_word: str, sentence_context: str
) -> WordDefinitionResult:
    return await _global_definitions_engine.lookup_contextual_definition(
        target_word, sentence_context
    )


async def harvest_dictionary_senses(
    word: str,
) -> Tuple[str, Optional[str], List[WordSense]]:
    return await _global_definitions_engine.harvest_dictionary_senses(word)


def disambiguate_active_sense(
    candidate_senses: List[WordSense], target_word: str, sentence: str
) -> List[WordSense]:
    return _global_definitions_engine.disambiguate_active_sense(
        candidate_senses, target_word, sentence
    )
