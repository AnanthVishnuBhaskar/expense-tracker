"""Claude calls used by the pipeline. Tests swap in a fake that implements ReceiptAI."""

import base64
import json
import logging
import os
from typing import Protocol

import anthropic
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.pipeline.schemas import CategoryChoice, QualityCheck, ReceiptExtraction

log = logging.getLogger(__name__)


class AIError(RuntimeError):
    pass


class ReceiptAI(Protocol):
    def check_quality(self, image: bytes, media_type: str) -> QualityCheck: ...

    def extract(
        self,
        image: bytes,
        media_type: str,
        *,
        home_country_hint: str | None,
        decoded_codes: list[str],
        previous_problems: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> tuple[ReceiptExtraction, str]: ...

    def categorize(
        self, merchant: str, items: list[str], categories: list[str]
    ) -> CategoryChoice: ...


QUALITY_PROMPT = """Check this photo before we read it as a receipt.
Say whether it is a receipt, bill or invoice, whether the merchant and total are readable,
how many receipts it contains, and give one short retake tip if the photo needs it."""

EXTRACTION_PROMPT = """Read this receipt and extract every useful detail into the schema.

Rules:
- Copy text exactly as printed; never invent values. For anything not on the receipt use null,
  or an empty string for text and 0 for fees, tips, discounts and rounding.
- Work out the country from the address, currency symbol, tax IDs, phone codes and language,
  then read dates and numbers the way that country writes them (e.g. 03/04 is 3 April in India
  and the UK, March 4 in the US; 1.234,56 is one thousand two hundred thirty-four in Germany).
- Amounts are plain numbers in the receipt's currency. Keep each tax line separate (e.g. CGST
  and SGST). Report discounts as positive numbers.
- Record only the last 4 digits of any card number.
- Put every other useful printed detail in `extras`, and transcribe the full receipt in
  `full_text`.
- List any field you had to guess in `low_confidence_fields`."""

CATEGORY_PROMPT = """Pick the best category for this purchase from the allowed list.
Merchant: {merchant}
Items: {items}
Allowed categories: {categories}
Use item_categories only when the items clearly span different categories."""


class AnthropicReceiptAI:
    def __init__(self, settings: Settings, client: anthropic.Anthropic | None = None):
        self.settings = settings
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        # Built on first use so a missing key shows up as a clear error on the receipt.
        if self._client is None:
            key = self.settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise AIError(
                    "No Claude API key is set. Add ANTHROPIC_API_KEY to backend/.env and restart."
                )
            # A receipt should never hang: give up after 90s (one retry) and show an error instead.
            self._client = anthropic.Anthropic(api_key=key, timeout=90, max_retries=1)
        return self._client

    def _image_block(self, image: bytes, media_type: str) -> dict:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image).decode("ascii"),
            },
        }

    def _call(self, method, **kwargs):
        try:
            return method(max_tokens=16000, **kwargs)
        except anthropic.RateLimitError as e:
            raise AIError("Claude rate limit reached, try again shortly") from e
        except anthropic.AuthenticationError as e:
            raise AIError(
                "Claude rejected the API key. Check ANTHROPIC_API_KEY in backend/.env."
            ) from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APITimeoutError as e:
            raise AIError("Claude took too long to answer, try again") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Could not reach the Claude API") from e

    @staticmethod
    def _check_stop(response) -> None:
        if response.stop_reason == "refusal":
            raise AIError("Claude declined to process this image")
        if response.stop_reason == "max_tokens":
            raise AIError("Claude returned an incomplete result")

    def _parse[T: BaseModel](self, *, model: str, content: list, schema: type[T], **kwargs) -> T:
        """Small schemas: the API enforces the shape for us."""
        log.info("claude %s: asking for %s", model, schema.__name__)
        response = self._call(
            self.client.beta.messages.parse,
            model=model,
            messages=[{"role": "user", "content": content}],
            output_format=schema,
            **kwargs,
        )
        self._check_stop(response)
        if response.parsed_output is None:
            raise AIError("Claude returned an incomplete result")
        log.info("claude %s request_id=%s usage=%s", model, response._request_id, response.usage)
        return response.parsed_output

    def _json[T: BaseModel](self, *, model: str, content: list, schema: type[T], **kwargs) -> T:
        """Large schemas: too big for the API to enforce, so we ask for JSON and validate it here."""
        log.info("claude %s: asking for %s (json)", model, schema.__name__)
        instructions = (
            "Reply with only a JSON object (no prose, no code fences) matching this JSON Schema:\n"
            + json.dumps(schema.model_json_schema(), separators=(",", ":"))
        )
        messages = [{"role": "user", "content": [*content, {"type": "text", "text": instructions}]}]
        for attempt in range(2):
            response = self._call(
                self.client.beta.messages.create, model=model, messages=messages, **kwargs
            )
            self._check_stop(response)
            log.info(
                "claude %s request_id=%s usage=%s", model, response._request_id, response.usage
            )
            text = "".join(b.text for b in response.content if b.type == "text")
            try:
                return schema.model_validate_json(_json_object(text))
            except (ValueError, ValidationError) as e:
                if attempt:
                    raise AIError("Claude's answer could not be understood, try again") from e
                log.warning("claude %s: invalid JSON, asking again: %s", model, e)
                messages += [
                    {"role": "assistant", "content": text or "{}"},
                    {
                        "role": "user",
                        "content": f"That JSON did not match the schema:\n{str(e)[:2000]}\n"
                        "Reply again with only the corrected JSON object.",
                    },
                ]
        raise AssertionError("unreachable")

    def check_quality(self, image: bytes, media_type: str) -> QualityCheck:
        return self._parse(
            model=self.settings.fast_model,
            content=[
                self._image_block(image, media_type),
                {"type": "text", "text": QUALITY_PROMPT},
            ],
            schema=QualityCheck,
            output_config={"effort": "low"},
        )

    def extract(
        self,
        image: bytes,
        media_type: str,
        *,
        home_country_hint: str | None,
        decoded_codes: list[str],
        previous_problems: list[str] | None = None,
        categories: list[str] | None = None,
    ) -> tuple[ReceiptExtraction, str]:
        text = EXTRACTION_PROMPT
        if categories:
            # Picking the category here saves a separate call.
            text += "\n\nSpending categories to choose from: " + ", ".join(categories)
        if home_country_hint:
            text += f"\n\nThe user lives in {home_country_hint}; receipts may be from anywhere."
        if decoded_codes:
            text += "\n\nCodes decoded from the image:\n" + "\n".join(decoded_codes)
        if previous_problems:
            text += (
                "\n\nA previous reading failed these checks; re-read the receipt carefully:\n- "
                + "\n- ".join(previous_problems)
            )
        effort = (
            self.settings.retry_effort if previous_problems else self.settings.extraction_effort
        )
        model = self.settings.extraction_model
        result = self._json(
            model=model,
            content=[self._image_block(image, media_type), {"type": "text", "text": text}],
            schema=ReceiptExtraction,
            output_config={"effort": effort},
            # On a safety decline, let the API retry on a suitable fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        return result, model

    def categorize(self, merchant: str, items: list[str], categories: list[str]) -> CategoryChoice:
        prompt = CATEGORY_PROMPT.format(
            merchant=merchant,
            items="; ".join(f"{i}: {d}" for i, d in enumerate(items[:60])) or "(none listed)",
            categories=", ".join(categories),
        )
        return self._parse(
            model=self.settings.fast_model,
            content=[{"type": "text", "text": prompt}],
            schema=CategoryChoice,
            output_config={"effort": "low"},
        )


def _json_object(text: str) -> str:
    """The outermost {...} in a reply, tolerating code fences or stray prose around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    return text[start : end + 1]
