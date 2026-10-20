"""Curated, hand-reviewed list of GCP/Vertex AI model identifiers for the Semantic tab.

Only Google publishes the authoritative, current Model Garden listing - this is a
starting point so a developer picks a real, spellable model id instead of guessing.
`validated` means this project's own scripts (`scripts/probe_vertex.py`) and benchmark
reports (`reports/*.md`) actually called that exact id against a live Vertex AI project
and got a real response. Everything else is Google-documented but unverified here -
check Vertex AI Model Garden for what's enabled in your project before relying on it.
"""
from __future__ import annotations

EMBEDDING_MODELS = [
    {
        "id": "gemini-embedding-001",
        "label": "Gemini Embedding 001 (recommended)",
        "dimensions": "3072 by default through this app; the benchmark scripts in reports/*.md "
                       "called the API directly with output_dimensionality=768 - "
                       "graphkit.semantic_workflow.GeminiEmbeddings does not set that parameter, "
                       "so embedding here returns the model's full 3072-dim vector instead.",
        "validated": True,
        "notes": "Confirmed reachable from this project's Vertex AI setup (scripts/probe_vertex.py). "
                 "Multilingual, supports RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY task types, which is "
                 "exactly what GeminiEmbeddings.documents()/question() send.",
    },
    {
        "id": "text-embedding-005",
        "label": "Vertex AI text-embedding-005",
        "dimensions": "768",
        "validated": False,
        "notes": "Google-documented Vertex AI Text Embeddings model, English-optimized. Not "
                 "exercised by this repo's scripts - confirm it's enabled in your project first.",
    },
    {
        "id": "text-multilingual-embedding-002",
        "label": "Vertex AI text-multilingual-embedding-002",
        "dimensions": "768",
        "validated": False,
        "notes": "Google-documented multilingual Vertex AI Text Embeddings model. Not exercised "
                 "by this repo's scripts.",
    },
    {
        "id": "textembedding-gecko@003",
        "label": "textembedding-gecko@003 (legacy)",
        "dimensions": "768",
        "validated": False,
        "notes": "Older Vertex AI embedding model Google is phasing out in favor of "
                 "gemini-embedding-001 / text-embedding-005. Only pick this to match an existing "
                 "index you can't re-embed yet.",
    },
]

GENERATION_MODELS = [
    {
        "id": "gemini-3.5-flash",
        "label": "Gemini 3.5 Flash (recommended)",
        "validated": True,
        "notes": "This project's default (GRAPHKIT_MODEL env var) and the model actually used "
                 "in reports/cloud-benchmark-2026-10-19.md and reports/bqml-customers-benchmark-"
                 "2026-10-19.md - confirmed reachable from this project's Vertex AI setup.",
    },
    {
        "id": "gemini-3-flash-preview",
        "label": "Gemini 3 Flash (preview)",
        "validated": False,
        "notes": "Listed as a fallback candidate in scripts/probe_vertex.py, tried only if "
                 "3.5-flash isn't available in your project. Not confirmed working here.",
    },
    {
        "id": "gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "validated": False,
        "notes": "Second fallback candidate in scripts/probe_vertex.py. GA model, but not "
                 "confirmed working against this project's Vertex AI setup.",
    },
    {
        "id": "gemini-2.5-pro",
        "label": "Gemini 2.5 Pro",
        "validated": False,
        "notes": "Higher-quality, slower alternative worth trying for harder --llm question "
                 "generation or explanation steps. Not exercised by this repo's scripts.",
    },
]

DEFAULTS = {"embedding_model": "gemini-embedding-001", "generation_model": "gemini-3.5-flash"}

NOTE = (
    "There is no required pairing between the embedding model and the generation model - "
    "any Gemini generation model can read context produced by any embedding model. The one "
    "hard rule the code enforces (graphkit/agent.py DatasetAgent) is that a question must be "
    "embedded with the exact same model used to embed the catalog, or it's rejected."
)
