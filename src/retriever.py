"""Retriever (the RAG layer): pure-Python TF-IDF over a small knowledge base and the catalog.

What retrieval does in Vibify (it is load-bearing, not decoration):
  * resolve_genre(): exact name -> alias -> TF-IDF semantic match -> none.
  * neighbors(): related-genre weights from the knowledge files; the scorer turns them into
    fuzzy genre credit, so editing a weight in knowledge/ changes scores and rankings.
  * snippets(): passages handed to the explainer so explanations cite their source file.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from src.config import DEFAULT_CONFIG, STOPWORDS, Config

_TOKEN = re.compile(r"[a-z0-9]+")


class KnowledgeBaseError(ValueError):
    pass


def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class TfidfIndex:
    """Minimal TF-IDF + cosine similarity index."""

    def __init__(self, texts: Sequence[str]):
        docs = [Counter(tokenize(t)) for t in texts]
        n = len(docs)
        df: Counter = Counter()
        for d in docs:
            df.update(d.keys())
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.vectors = [self._vec(d) for d in docs]

    def _vec(self, counts: Counter) -> Dict[str, float]:
        v = {t: (1.0 + math.log(c)) * self.idf[t] for t, c in counts.items() if t in self.idf}
        norm = math.sqrt(sum(x * x for x in v.values()))
        return {t: x / norm for t, x in v.items()} if norm else {}

    def scores(self, query: str) -> List[float]:
        q = self._vec(Counter(tokenize(query)))
        if not q:
            return [0.0] * len(self.vectors)
        return [sum(w * v.get(t, 0.0) for t, w in q.items()) for v in self.vectors]


@dataclass
class ResolvedGenre:
    canonical: Optional[str]
    method: str  # exact | alias | semantic | none
    score: float


@dataclass
class Snippet:
    source_file: str
    text: str
    score: float


def render_song(song: Dict) -> str:
    return (f"{song['title']} by {song['artist']} genre {song['genre']} mood {song['mood']} "
            f"energy {song['energy']:.2f} tempo {song['tempo_bpm']:.0f} acousticness {song['acousticness']:.2f}")


class KnowledgeBase:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        self.genres: Dict[str, Dict] = {}          # canonical -> {aliases, related, prose, file}
        self.alias_map: Dict[str, str] = {}
        self.chunks: List[Snippet] = []
        self._related: Dict[str, Dict[str, float]] = {}
        self._genre_names: List[str] = []
        self._genre_index: Optional[TfidfIndex] = None
        self._chunk_index: Optional[TfidfIndex] = None
        self._catalog: List[Dict] = []
        self._catalog_index: Optional[TfidfIndex] = None

    # ---------- loading ----------
    @classmethod
    def load(cls, knowledge_dir: str, config: Config = DEFAULT_CONFIG) -> "KnowledgeBase":
        kb = cls(config)
        root = Path(knowledge_dir)
        gdir = root / "genres"
        if not gdir.is_dir():
            raise KnowledgeBaseError(f"knowledge directory missing: {gdir}")
        for path in sorted(gdir.glob("*.md")):
            kb._load_genre_file(path, f"genres/{path.name}")
        if not kb.genres:
            raise KnowledgeBaseError(f"no genre files found in {gdir}")
        for name in ("moods.md", "energy_guide.md", "acousticness_guide.md"):
            p = root / name
            if p.exists():
                for para in re.split(r"\n\s*\n", p.read_text(encoding="utf-8")):
                    if para.strip():
                        kb.chunks.append(Snippet(name, para.strip(), 0.0))
        kb._build()
        return kb

    def _load_genre_file(self, path: Path, rel: str) -> None:
        raw = path.read_text(encoding="utf-8")
        if "\n---" not in raw:
            raise KnowledgeBaseError(f"{rel}: missing '---' header separator")
        head, prose = raw.split("\n---", 1)
        meta: Dict[str, str] = {}
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
        if not meta.get("genre"):
            raise KnowledgeBaseError(f"{rel}: missing 'genre:' header")
        genre = meta["genre"].lower()
        aliases = [a.strip().lower() for a in meta.get("aliases", "").split(",") if a.strip()]
        related: Dict[str, float] = {}
        for part in meta.get("related", "").split(","):
            if "=" in part:
                name, w = part.rsplit("=", 1)
                try:
                    weight = float(w)
                except ValueError:
                    raise KnowledgeBaseError(f"{rel}: bad related weight {part.strip()!r}") from None
                if not 0.0 < weight < 1.0:
                    raise KnowledgeBaseError(f"{rel}: related weight must be in (0,1): {part.strip()!r}")
                related[name.strip().lower()] = weight
        prose = prose.lstrip("-").strip()
        self.genres[genre] = {"aliases": aliases, "related": related, "prose": prose, "file": rel}
        for a in aliases:
            self.alias_map[a] = genre
        for para in re.split(r"\n\s*\n", prose):
            if para.strip():
                self.chunks.append(Snippet(rel, para.strip(), 0.0))

    def _build(self) -> None:
        self._genre_names = sorted(self.genres)
        texts = [f"{g} {' '.join(self.genres[g]['aliases'])} {self.genres[g]['prose']}" for g in self._genre_names]
        self._genre_index = TfidfIndex(texts)
        self._chunk_index = TfidfIndex([c.text for c in self.chunks])
        sym: Dict[str, Dict[str, float]] = {g: {} for g in self.genres}
        for g, info in self.genres.items():
            for other, w in info["related"].items():
                if other not in self.genres or other == g:
                    continue
                sym[g][other] = max(sym[g].get(other, 0.0), w)
                sym[other][g] = max(sym[other].get(g, 0.0), w)
        self._related = sym

    # ---------- API ----------
    def genre_names(self) -> List[str]:
        return list(self._genre_names)

    def resolve_genre(self, name: str) -> ResolvedGenre:
        key = re.sub(r"\s+", " ", (name or "").strip().lower())
        if not key:
            return ResolvedGenre(None, "none", 0.0)
        if key in self.genres:
            return ResolvedGenre(key, "exact", 1.0)
        if key in self.alias_map:
            return ResolvedGenre(self.alias_map[key], "alias", 1.0)
        scores = self._genre_index.scores(key)
        best = max(range(len(scores)), key=lambda i: (scores[i], -i))
        if scores[best] >= self.config.semantic_min_similarity:
            return ResolvedGenre(self._genre_names[best], "semantic", round(scores[best], 4))
        return ResolvedGenre(None, "none", round(scores[best], 4))

    def neighbors(self, canonical: str) -> Dict[str, float]:
        return dict(self._related.get(canonical, {}))

    def snippets(self, query: str, k: int = 3) -> List[Snippet]:
        scores = self._chunk_index.scores(query)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        return [Snippet(self.chunks[i].source_file, self.chunks[i].text, round(scores[i], 4))
                for i in order[:k] if scores[i] > 0]

    def genre_snippet(self, genre: str) -> Optional[Snippet]:
        info = self.genres.get(genre)
        if not info:
            return None
        first = re.split(r"\n\s*\n", info["prose"])[0].strip()
        return Snippet(info["file"], first, 1.0)

    # ---------- catalog retrieval ----------
    def index_catalog(self, songs: List[Dict]) -> None:
        self._catalog = list(songs)
        self._catalog_index = TfidfIndex([render_song(s) for s in songs])

    def search_catalog(self, query: str, k: int = 5) -> List[Dict]:
        if not self._catalog_index:
            return []
        scores = self._catalog_index.scores(query)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], self._catalog[i]["id"]))
        return [self._catalog[i] for i in order[:k] if scores[i] > 0]
