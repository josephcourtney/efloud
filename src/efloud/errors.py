from __future__ import annotations


class EfloudError(Exception):
    """Base class for stable public Efloud failures."""


class RepositoryError(EfloudError):
    """Repository creation, opening, or access failed."""


class RepositoryOpenError(RepositoryError):
    """A repository could not be created or opened as requested."""


class RepositorySchemaError(RepositoryOpenError):
    """Repository metadata uses an unsupported schema."""


class RepositoryBusyError(RepositoryOpenError):
    """Writable repository access could not obtain coordination authority."""


class ExecutionError(EfloudError):
    """Acquisition or execution failed before producing a successful result."""


class DatasetError(EfloudError):
    """Dataset resolution, freezing, or lookup failed."""


class DatasetConstraintError(DatasetError):
    """Dataset coherence constraints were not satisfied."""


class VerificationError(EfloudError):
    """Stored or detached content could not be verified."""


class IntegrityError(VerificationError):
    """Content disagrees with required integrity evidence."""


class ExportError(EfloudError):
    """Dataset export planning or publication failed."""


__all__ = [
    "DatasetConstraintError",
    "DatasetError",
    "EfloudError",
    "ExecutionError",
    "ExportError",
    "IntegrityError",
    "RepositoryBusyError",
    "RepositoryError",
    "RepositoryOpenError",
    "RepositorySchemaError",
    "VerificationError",
]
