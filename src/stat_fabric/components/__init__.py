"""Statistics components. Importing this package declares them via ``@component``."""

from . import descriptive, inferential, multivariate, temporal  # noqa: F401
from .base import TableComponent, TableResult

__all__ = ["TableComponent", "TableResult"]
