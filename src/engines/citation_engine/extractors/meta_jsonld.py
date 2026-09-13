"""Lightweight streaming HTML meta-tag and Schema.org JSON-LD extractor."""

from __future__ import annotations

import json
import logging
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from engines.citation_engine.extractors.base import BaseExtractor
from engines.citation_engine.models import (
    Author,
    CitationDate,
    FieldConfidence,
    ReferenceMetadata,
    SourceType,
)
from engines.citation_engine.normalizer import (
    clean_doi,
    clean_isbn,
    clean_url,
    parse_author,
    parse_authors_list,
    parse_date_string,
    sanitize_title,
)

log = logging.getLogger("citation_engine.meta_jsonld")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 (ResearchAssistantBot/1.0)"
)
MAX_HEAD_BYTES = 131072  # 128 KB max stream threshold for <head>


class HeadHTMLParser(HTMLParser):
    """Zero-dependency streaming HTML parser extracting <title>, <meta>, <link>, and JSON-LD."""

    def __init__(self):
        super().__init__()
        self.title: Optional[str] = None
        self.in_title: bool = False
        self.meta_tags: List[Dict[str, str]] = []
        self.canonical_url: Optional[str] = None
        self.json_ld_raw: List[str] = []
        self.in_json_ld: bool = False
        self._current_json_ld: List[str] = []
        self.time_tags: List[Dict[str, str]] = []
        self.head_closed: bool = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        tag_lower = tag.lower()

        if tag_lower == "title":
            self.in_title = True
        elif tag_lower == "meta":
            self.meta_tags.append(attr_dict)
        elif tag_lower == "link":
            rel = attr_dict.get("rel", "").lower()
            if rel == "canonical" and "href" in attr_dict:
                self.canonical_url = attr_dict["href"]
        elif tag_lower == "script":
            script_type = attr_dict.get("type", "").lower()
            if "application/ld+json" in script_type:
                self.in_json_ld = True
                self._current_json_ld = []
        elif tag_lower == "time":
            if "datetime" in attr_dict:
                self.time_tags.append(attr_dict)

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self.in_title = False
        elif tag_lower == "script" and self.in_json_ld:
            self.in_json_ld = False
            raw_text = "".join(self._current_json_ld).strip()
            if raw_text:
                self.json_ld_raw.append(raw_text)
            self._current_json_ld = []
        elif tag_lower == "head":
            self.head_closed = True

    def handle_data(self, data: str):
        if self.in_title:
            self.title = (self.title or "") + data
        elif self.in_json_ld:
            self._current_json_ld.append(data)


class MetaJsonLdExtractor(BaseExtractor):
    """Extracts rich metadata via OpenGraph, Highwire Press, Dublin Core, and Schema.org JSON-LD."""

    def __init__(self, timeout_secs: float = 8.0, user_agent: str = DEFAULT_USER_AGENT):
        self._timeout = timeout_secs
        self._user_agent = user_agent

    def can_handle(self, target: str) -> bool:
        """Handles HTTP and HTTPS URLs."""
        clean = (target or "").strip().lower()
        return clean.startswith("http://") or clean.startswith("https://")

    async def extract(self, target: str) -> Optional[ReferenceMetadata]:
        url = clean_url(target)
        if not url:
            return None

        headers = {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        html_chunks: List[str] = []
        total_bytes = 0
        final_url = url
        last_modified_hdr: Optional[str] = None

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers=headers,
            ) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code >= 400:
                        log.debug("HTTP %s returned for %s", resp.status_code, url)
                        return None

                    final_url = str(resp.url)
                    last_modified_hdr = resp.headers.get("last-modified")

                    async for chunk in resp.aiter_text():
                        html_chunks.append(chunk)
                        total_bytes += len(chunk.encode("utf-8", errors="ignore"))
                        # Short-circuit once </head> is found or limit exceeded
                        if "</head>" in chunk.lower() or "</HEAD>" in chunk or total_bytes >= MAX_HEAD_BYTES:
                            break
        except Exception as exc:
            log.debug("Streaming fetch failed for %s: %s", url, exc)
            return None

        html_content = "".join(html_chunks)
        if not html_content.strip():
            return None

        parser = HeadHTMLParser()
        try:
            parser.feed(html_content)
        except Exception as exc:
            log.debug("HTMLParser warning on %s: %s", url, exc)

        return self.parse_html_metadata(
            html_parser=parser,
            canonical_url=final_url,
            last_modified_header=last_modified_hdr,
        )

    def parse_html_metadata(
        self,
        html_parser: HeadHTMLParser,
        canonical_url: str,
        last_modified_header: Optional[str] = None,
    ) -> ReferenceMetadata:
        """Consolidates parsed head tags and JSON-LD according to strict precedence rules."""
        field_conf: Dict[str, FieldConfidence] = {}
        warnings: List[str] = []

        # 1. Parse JSON-LD structures
        jsonld_data = self._extract_jsonld(html_parser.json_ld_raw)

        # 2. Extract meta maps
        meta_dict: Dict[str, List[str]] = {}
        for m in html_parser.meta_tags:
            name_or_prop = m.get("property") or m.get("name") or m.get("itemprop")
            content = m.get("content") or m.get("value")
            if name_or_prop and content:
                key = name_or_prop.strip().lower()
                meta_dict.setdefault(key, []).append(content.strip())

        # 3. Source Type Classification
        source_type = self._classify_source_type(jsonld_data, meta_dict)

        # 4. Resolve Title
        title, title_conf = self._resolve_title(jsonld_data, meta_dict, html_parser.title)
        field_conf["title"] = title_conf

        # 5. Resolve Authors
        authors, author_conf, author_warn = self._resolve_authors(jsonld_data, meta_dict)
        if authors:
            field_conf["authors"] = author_conf
        if author_warn:
            warnings.append(author_warn)

        # 6. Resolve Date (Hierarchy: json-ld -> og/article -> time tags -> last-modified)
        date, date_conf, date_warn = self._resolve_date(jsonld_data, meta_dict, html_parser.time_tags, last_modified_header)
        field_conf["date"] = date_conf
        if date_warn:
            warnings.append(date_warn)

        # 7. Resolve Container Title / Publisher / Website Name
        container_title, publisher = self._resolve_container_and_publisher(jsonld_data, meta_dict)

        # If no author found, check if corporate author can be assigned from publisher/site_name
        if not authors:
            org_author = publisher or container_title
            if org_author and org_author.lower() not in {"website", "home", "article"}:
                authors = [Author(family=org_author, is_corporate=True)]
                field_conf["authors"] = FieldConfidence.MEDIUM
                warnings.append(f"No personal author found; attributed to organization '{org_author}'")
            else:
                warnings.append("No author or organization found; title will shift to author position per style guidelines")

        # 8. Resolve Academic Container Fields (volume, issue, pages, doi, isbn)
        volume = self._get_first_meta(meta_dict, ["citation_volume"])
        issue = self._get_first_meta(meta_dict, ["citation_issue"])
        first_page = self._get_first_meta(meta_dict, ["citation_firstpage"])
        last_page = self._get_first_meta(meta_dict, ["citation_lastpage"])
        pages = f"{first_page}-{last_page}" if (first_page and last_page) else (first_page or last_page)

        # Identifiers
        raw_doi = self._get_first_meta(meta_dict, ["citation_doi", "dc.identifier", "dc.identifier.doi"])
        if not raw_doi and jsonld_data:
            raw_doi = jsonld_data.get("doi") or jsonld_data.get("identifier")
        doi = clean_doi(raw_doi)

        raw_isbn = self._get_first_meta(meta_dict, ["citation_isbn", "dc.identifier.isbn"])
        if not raw_isbn and jsonld_data:
            raw_isbn = jsonld_data.get("isbn")
        isbn = clean_isbn(raw_isbn)

        # Canonical URL
        resolved_url = (
            html_parser.canonical_url
            or self._get_first_meta(meta_dict, ["og:url", "twitter:url"])
            or canonical_url
        )
        resolved_url = clean_url(resolved_url)

        # Calculate composite confidence score
        confidence_weights = {
            FieldConfidence.AUTHORITATIVE: 1.0,
            FieldConfidence.HIGH: 0.85,
            FieldConfidence.MEDIUM: 0.65,
            FieldConfidence.LOW: 0.40,
        }
        scores = [confidence_weights.get(fc, 0.5) for fc in field_conf.values()]
        composite_score = round(sum(scores) / len(scores), 2) if scores else 0.60

        return ReferenceMetadata(
            title=sanitize_title(title),
            authors=authors,
            date=date,
            source_type=source_type,
            container_title=container_title,
            publisher=publisher,
            volume=volume,
            issue=issue,
            pages=pages,
            doi=doi,
            isbn=isbn,
            url=resolved_url,
            confidence_score=composite_score,
            field_confidence=field_conf,
            provenance_warnings=warnings,
            raw_data={
                "meta": meta_dict,
                "json_ld": jsonld_data,
            },
        )

    def _extract_jsonld(self, raw_scripts: List[str]) -> Optional[Dict[str, Any]]:
        """Parses JSON-LD scripts and locates relevant Article or CreativeWork schemas."""
        for script in raw_scripts:
            try:
                data = json.loads(script)
            except Exception:
                continue

            # If array of objects
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    items = data["@graph"]
                else:
                    items = [data]

            for item in items:
                if not isinstance(item, dict):
                    continue
                type_val = item.get("@type")
                if isinstance(type_val, list):
                    types = [str(t).lower() for t in type_val]
                elif isinstance(type_val, str):
                    types = [type_val.lower()]
                else:
                    types = []

                if any(t in types for t in [
                    "scholarlyarticle", "newsarticle", "blogposting", "techarticle",
                    "article", "report", "book", "webpage", "creativework",
                ]):
                    return item

        return None

    def _classify_source_type(
        self,
        jsonld: Optional[Dict[str, Any]],
        meta: Dict[str, List[str]],
    ) -> SourceType:
        """Determines categorical SourceType for citation formatting."""
        # 1. Highwire Press or Scholarly Article presence
        if any(k.startswith("citation_") for k in meta.keys()):
            return SourceType.ACADEMIC_PAPER

        if jsonld:
            jtype = str(jsonld.get("@type", "")).lower()
            if "scholarlyarticle" in jtype:
                return SourceType.ACADEMIC_PAPER
            if "newsarticle" in jtype:
                return SourceType.NEWS_ARTICLE
            if "blogposting" in jtype or "blog" in jtype:
                return SourceType.BLOG_POST
            if "book" in jtype:
                return SourceType.BOOK
            if "report" in jtype:
                return SourceType.REPORT

        og_type = self._get_first_meta(meta, ["og:type"]) or ""
        if "article" in og_type:
            section = self._get_first_meta(meta, ["article:section"]) or ""
            if any(term in section.lower() for term in ["news", "politics", "world", "business"]):
                return SourceType.NEWS_ARTICLE
            return SourceType.NEWS_ARTICLE

        return SourceType.WEBPAGE

    def _resolve_title(
        self,
        jsonld: Optional[Dict[str, Any]],
        meta: Dict[str, List[str]],
        parser_title: Optional[str],
    ) -> Tuple[str, FieldConfidence]:
        """Resolves page or article title in order of authoritative precedence."""
        # 1. JSON-LD headline or name
        if jsonld:
            j_title = jsonld.get("headline") or jsonld.get("name")
            if j_title and isinstance(j_title, str) and len(j_title.strip()) > 2:
                return j_title.strip(), FieldConfidence.AUTHORITATIVE

        # 2. Highwire / Dublin Core
        citation_title = self._get_first_meta(meta, ["citation_title", "dc.title"])
        if citation_title:
            return citation_title, FieldConfidence.HIGH

        # 3. OpenGraph / Twitter
        og_title = self._get_first_meta(meta, ["og:title", "twitter:title"])
        if og_title:
            return og_title, FieldConfidence.HIGH

        # 4. Fallback: <title> tag
        if parser_title and parser_title.strip():
            return parser_title.strip(), FieldConfidence.MEDIUM

        return "Untitled", FieldConfidence.LOW

    def _resolve_authors(
        self,
        jsonld: Optional[Dict[str, Any]],
        meta: Dict[str, List[str]],
    ) -> Tuple[List[Author], FieldConfidence, Optional[str]]:
        """Extracts structured authors without guessing from body text."""
        authors: List[Author] = []

        # 1. JSON-LD Authors
        if jsonld and "author" in jsonld:
            j_auth = jsonld["author"]
            if isinstance(j_auth, list):
                for a in j_auth:
                    authors.extend(self._parse_single_jsonld_author(a))
            else:
                authors.extend(self._parse_single_jsonld_author(j_auth))

            if authors:
                return authors, FieldConfidence.AUTHORITATIVE, None

        # 2. Highwire Press Authors (e.g. repeated <meta name="citation_author" content="...">)
        hw_authors = meta.get("citation_author", [])
        if hw_authors:
            for a_str in hw_authors:
                authors.append(parse_author(a_str))
            return authors, FieldConfidence.HIGH, None

        # 3. Dublin Core Creator
        dc_creators = meta.get("dc.creator", []) or meta.get("dcterms.creator", [])
        if dc_creators:
            for c_str in dc_creators:
                authors.extend(parse_authors_list(c_str))
            return authors, FieldConfidence.HIGH, None

        # 4. OpenGraph article:author or standard author meta
        og_authors = meta.get("article:author", []) or meta.get("author", [])
        if og_authors:
            for a_str in og_authors:
                # Discard URL slugs passed as article:author (e.g. facebook profile links)
                if a_str.startswith("http://") or a_str.startswith("https://"):
                    continue
                authors.extend(parse_authors_list(a_str))
            if authors:
                return authors, FieldConfidence.HIGH, None

        return [], FieldConfidence.LOW, None

    def _parse_single_jsonld_author(self, a_val: Any) -> List[Author]:
        if isinstance(a_val, str):
            return parse_authors_list(a_val)
        if isinstance(a_val, dict):
            a_type = str(a_val.get("@type", "")).lower()
            if a_type == "organization":
                name = a_val.get("name", "").strip()
                return [Author(family=name, is_corporate=True)] if name else []

            name = a_val.get("name")
            given = a_val.get("givenName") or ""
            family = a_val.get("familyName") or ""
            if family and given:
                return [Author(family=family.strip(), given=given.strip())]
            if name:
                return [parse_author(name)]
        return []

    def _resolve_date(
        self,
        jsonld: Optional[Dict[str, Any]],
        meta: Dict[str, List[str]],
        time_tags: List[Dict[str, str]],
        last_modified_header: Optional[str],
    ) -> Tuple[CitationDate, FieldConfidence, Optional[str]]:
        """Strict date resolution hierarchy: JSON-LD/meta pub -> <time> -> modified -> Last-Modified."""
        # 1. JSON-LD datePublished
        if jsonld:
            j_date = jsonld.get("datePublished") or jsonld.get("dateCreated")
            if j_date:
                dt = parse_date_string(str(j_date))
                if dt.has_date:
                    return dt, FieldConfidence.AUTHORITATIVE, None

        # 2. Meta published time (Highwire, Dublin Core, OpenGraph)
        pub_meta = self._get_first_meta(meta, [
            "article:published_time",
            "citation_publication_date",
            "citation_date",
            "dc.date",
            "dc.date.issued",
            "publication_date",
            "pubdate",
        ])
        if pub_meta:
            dt = parse_date_string(pub_meta)
            if dt.has_date:
                return dt, FieldConfidence.HIGH, None

        # 3. HTML <time datetime="..."> in <head>
        for t in time_tags:
            dt_str = t.get("datetime")
            if dt_str:
                dt = parse_date_string(dt_str)
                if dt.has_date:
                    return dt, FieldConfidence.MEDIUM, "Date extracted from HTML <time> tag"

        # 4. JSON-LD / Meta dateModified
        if jsonld and jsonld.get("dateModified"):
            dt = parse_date_string(str(jsonld["dateModified"]))
            if dt.has_date:
                return dt, FieldConfidence.MEDIUM, "Date inferred from article modification timestamp"

        mod_meta = self._get_first_meta(meta, ["article:modified_time", "og:updated_time"])
        if mod_meta:
            dt = parse_date_string(mod_meta)
            if dt.has_date:
                return dt, FieldConfidence.MEDIUM, "Date inferred from article modification timestamp"

        # 5. Last-Modified HTTP header
        if last_modified_header:
            dt = parse_date_string(last_modified_header)
            if dt.has_date:
                return dt, FieldConfidence.LOW, "Date inferred from HTTP Last-Modified header"

        return CitationDate(has_date=False), FieldConfidence.LOW, "No publication date found; formatted as (n.d.)"

    def _resolve_container_and_publisher(
        self,
        jsonld: Optional[Dict[str, Any]],
        meta: Dict[str, List[str]],
    ) -> Tuple[Optional[str], Optional[str]]:
        container_title: Optional[str] = None
        publisher: Optional[str] = None

        # 1. Highwire Press journal title & publisher
        container_title = self._get_first_meta(meta, ["citation_journal_title"])
        publisher = self._get_first_meta(meta, ["citation_publisher", "dc.publisher"])

        # 2. JSON-LD publication / isPartOf / publisher
        if jsonld:
            if not container_title:
                is_part_of = jsonld.get("isPartOf")
                if isinstance(is_part_of, dict):
                    container_title = is_part_of.get("name")
                elif isinstance(is_part_of, str):
                    container_title = is_part_of

            if not publisher:
                pub_obj = jsonld.get("publisher")
                if isinstance(pub_obj, dict):
                    publisher = pub_obj.get("name")
                elif isinstance(pub_obj, str):
                    publisher = pub_obj

        # 3. OpenGraph site_name
        if not container_title:
            container_title = self._get_first_meta(meta, ["og:site_name", "twitter:site"])

        if not publisher and container_title:
            publisher = container_title

        return container_title, publisher

    def _get_first_meta(self, meta: Dict[str, List[str]], keys: List[str]) -> Optional[str]:
        for k in keys:
            vals = meta.get(k.lower())
            if vals and vals[0].strip():
                return vals[0].strip()
        return None
