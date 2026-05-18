"""Stratum exception hierarchy."""
from __future__ import annotations


class StratumError(Exception):
    """Base exception for all Stratum errors."""


class ConfigError(StratumError):
    """Configuration problem."""


class PDFParseError(StratumError):
    """PDF parsing failed."""


class UnsupportedFileTypeError(StratumError):
    """File type not supported by this operation."""


class UnsupportedImageError(StratumError):
    """Image cannot be opened or is in an unsupported format."""


class EmbeddingError(StratumError):
    """Embedding generation failed."""


class QuotaExceededError(StratumError):
    """API quota or rate limit exceeded."""


class VectorDBError(StratumError):
    """Vector database operation failed."""


class FulltextError(StratumError):
    """Fulltext index operation failed."""


class MetaDBError(StratumError):
    """Metadata database operation failed."""


class LLMError(StratumError):
    """LLM call failed."""


class LLMRateLimitError(LLMError):
    """LLM rate limit hit."""


class IngestError(StratumError):
    """Document ingestion failed."""


class DuplicateSubstrateError(StratumError):
    """Attempt to ingest a substrate that already exists."""
