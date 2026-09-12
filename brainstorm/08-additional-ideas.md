# Additional Feature Ideas

Based on the architecture and capabilities already discussed, here are three additional functionalities that could extend the research aid:

---

## 1. Citation Context Rewriter

**Concept:** When the user highlights a citation (e.g., "(Smith et al., 2023)") or a paragraph containing citations, the tool analyzes the cited papers and suggests improved citation context — better phrasing that more accurately reflects what the cited paper actually says.

**How it works:**
1. User selects text containing citations
2. Tool extracts citation keys (via regex for common citation formats)
3. For each citation, fetches the paper's abstract and key findings from Semantic Scholar
4. LLM compares the user's phrasing against the paper's actual claims
5. Suggests rewording that more precisely reflects the cited work

**Example:**
- User wrote: "Recent studies have shown that X causes Y (Smith et al., 2023)."
- Tool finds Smith et al. 2023 actually found X correlates with Y under specific conditions
- Suggestion: "Under controlled conditions, Smith et al. (2023) found a correlation between X and Y."

**Value:** Prevents citation misrepresentation, improves academic rigor. No existing tool does this inline during writing.

**Technical requirements:**
- Semantic Scholar API (paper lookup by title/DOI)
- Citation extraction regex (handles APA, MLA, Chicago, BibTeX)
- LLM for comparison and rephrasing
- Overlay for showing before/after suggestions

---

## 2. Research Gap Detector

**Concept:** After the user has written a section of their paper, the tool analyzes the claims made and the citations used, then identifies potential gaps — claims that lack citation support, or areas where opposing evidence exists that the user has not acknowledged.

**How it works:**
1. User triggers on a full paragraph or section (Ctrl+Shift+G)
2. Tool extracts all claims and assertions from the text
3. For each claim, checks: is there a citation? If yes, does it support the claim?
4. For uncited claims, searches Semantic Scholar for relevant papers
5. Identifies claims with opposing evidence that should be acknowledged
6. Presents a "gap analysis" in the overlay

**Example output:**
```
Research Gap Analysis (3 issues found):

1. UNCITED CLAIM: "Quantum computing will revolutionize drug discovery"
   → 5 relevant papers found, 2 suggest limitations
   → Suggest citation: Zhang et al. 2024

2. MISSING COUNTERPOINT: "Our method outperforms all baselines"
   → Jones et al. 2023 found similar results but with caveats
   → Consider acknowledging: "However, Jones et al. note..."

3. OVERSTATED CLAIM: "This is the first study to..."
   → Chen et al. 2022 published similar work
   → Revise to: "This is one of the first studies to..."
```

**Value:** Acts as a peer review assistant before submission. Catches common academic writing mistakes. No existing tool does this automatically.

**Technical requirements:**
- LLM for claim extraction and assertion analysis
- Semantic Scholar API for evidence search
- Citation verification (ValiRef)
- Structured output in overlay

---

## 3. Multi-Language Research Bridge

**Concept:** When the user selects text in their non-native language (or a foreign paper), the tool provides: (a) translation with academic terminology preservation, (b) equivalent terminology in the user's writing language, and (c) related papers in the user's language.

**How it works:**
1. User selects text in a foreign language (or triggers on a foreign paper)
2. Tool detects language via langdetect or model auto-detection
3. Translates using a model that preserves academic terminology (not Google Translate generic output)
4. Maps domain-specific terms to equivalent terminology in user's language
5. Searches for related papers in the user's preferred language

**Example:**
- User selects German text: "Die Quantenverschränkung ermöglicht..."
- Tool translates: "Quantum entanglement enables..."
- Maps German CS terms to English equivalents
- Finds 3 related English papers on the same topic

**Value:** Massive for non-native English speakers (the majority of global researchers). Bridges language barriers in literature review. Preserves technical precision that generic translators lose.

**Technical requirements:**
- Language detection (langdetect or fasttext)
- Academic-tuned translation model (NLLB, MADLAD-400, or fine-tuned MarianMT)
- Domain terminology dictionary (field-specific mappings)
- Semantic Scholar API filtered by language
- Overlay with bilingual display

**Bonus:** Could also work in reverse — user writes in English, tool suggests how to phrase the same concept in German/Chinese/Spanish for international collaboration.

---

## Summary of Additional Ideas

| Feature | Complexity | Unique Value | Dependencies |
|---------|-----------|--------------|--------------|
| Citation Context Rewriter | Medium | Prevents citation misrepresentation | Semantic Scholar, LLM |
| Research Gap Detector | High | Automated pre-submission peer review | LLM, Semantic Scholar, ValiRef |
| Multi-Language Bridge | High | Serves non-native English speakers | Translation model, langdetect, Semantic Scholar |

All three leverage the same infrastructure (selection-hook, LLM, Semantic Scholar API, overlay UI) already planned for the core features. They require no new architectural components — just new processing pipelines.
