"""Local provider backed by Ollama.

Deliberately not implemented. This is the single stub the engineering rules
permit, and it fails loudly rather than quietly returning "no disagreements" —
a silent no-op provider would make consensus look like it had run and passed
when in fact nothing checked anything.

To finish it: call ``POST {ollama_base_url}/api/chat`` with the configured
vision model, the page or crop as a base64 image, and the same two prompts the
Anthropic provider uses, then parse the JSON reply into ``PageVerdict`` /
``CellReading``.
"""

from __future__ import annotations

from app.config import get_settings
from app.vlm.base import CellQuery, CellReading, PageVerdict, VLMProvider


class OllamaProvider(VLMProvider):
    """Placeholder for a local vision model served by Ollama."""

    name = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.base_url = base_url or settings.ollama_base_url
        self.model = model or settings.ollama_model

    def is_available(self) -> bool:
        """Always False: reporting otherwise would let consensus silently no-op."""
        return False

    def verify_page(self, page_png: bytes, cells: list[CellQuery]) -> PageVerdict:
        raise NotImplementedError(
            "The Ollama VLM provider is not implemented. Set VLM_PROVIDER=anthropic, "
            "or implement OllamaProvider.verify_page against "
            f"{self.base_url}/api/chat with model {self.model!r}."
        )

    def read_crop(self, crop_png: bytes) -> CellReading:
        raise NotImplementedError(
            "The Ollama VLM provider is not implemented. Set VLM_PROVIDER=anthropic, "
            "or implement OllamaProvider.read_crop against "
            f"{self.base_url}/api/chat with model {self.model!r}."
        )
