from __future__ import annotations

import json
import os
from dataclasses import replace
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import AIReview, ReviewReport


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class AIProviderError(RuntimeError):
    pass


def add_ai_review(
    report: ReviewReport,
    *,
    provider: str,
    model: str | None = None,
    timeout: float = 60,
    max_output_tokens: int = 900,
    ollama_url: str | None = None,
) -> ReviewReport:
    provider = provider.lower()
    resolved_model = resolve_model(provider, model)
    prompt = build_review_prompt(report)

    if provider == "openai":
        summary = generate_with_openai(
            prompt,
            model=resolved_model,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
        )
    elif provider == "ollama":
        summary = generate_with_ollama(
            prompt,
            model=resolved_model,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            base_url=ollama_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_URL,
        )
    else:
        raise AIProviderError(f"Unsupported AI provider: {provider}")

    return replace(
        report,
        ai_review=AIReview(
            provider=provider,
            model=resolved_model,
            status="generated",
            summary=summary.strip(),
        ),
    )


def attach_ai_error(
    report: ReviewReport,
    *,
    provider: str,
    model: str | None,
    error: str,
) -> ReviewReport:
    return replace(
        report,
        ai_review=AIReview(
            provider=provider,
            model=resolve_model(provider, model),
            status="error",
            summary="",
            error=error,
        ),
    )


def resolve_model(provider: str, model: str | None) -> str:
    if model:
        return model
    if provider == "openai":
        return os.environ.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
    if provider == "ollama":
        return os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
    return model or "unknown"


def build_review_prompt(report: ReviewReport) -> str:
    payload = {
        "repo_name": report.repo_name,
        "generated_at": report.generated_at,
        "overview": report.overview,
        "metrics": report.metrics,
        "framework_signals": report.framework_signals,
        "findings": [
            {
                "title": finding.title,
                "severity": finding.severity,
                "category": finding.category,
                "evidence": finding.evidence,
                "recommendation": finding.recommendation,
            }
            for finding in report.findings
        ],
    }
    review_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        "You are a senior software engineer reviewing a GitHub repository for a hiring portfolio.\n"
        "Use the structured analysis below. Do not invent files, frameworks, or risks that are not supported by the data.\n"
        "Return concise Markdown with exactly these sections:\n"
        "## AI Architecture Summary\n"
        "## Top Risks\n"
        "## Recommended Next Steps\n"
        "## Resume Pitch\n\n"
        "Rules:\n"
        "- Keep the tone practical and specific.\n"
        "- Mention evidence from the findings when discussing risks.\n"
        "- If there are no major risks, say so and suggest meaningful next improvements.\n"
        "- The Resume Pitch section should be 2-3 bullets suitable for a resume or interview.\n\n"
        f"Structured repository analysis:\n```json\n{review_json}\n```"
    )


def generate_with_openai(
    prompt: str,
    *,
    model: str,
    timeout: float,
    max_output_tokens: int,
) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AIProviderError("OPENAI_API_KEY is not set.")

    payload = {
        "model": model,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
    }
    data = _post_json(
        OPENAI_RESPONSES_URL,
        payload,
        timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    text = extract_openai_text(data)
    if not text:
        raise AIProviderError("OpenAI response did not contain text output.")
    return text


def generate_with_ollama(
    prompt: str,
    *,
    model: str,
    timeout: float,
    max_output_tokens: int,
    base_url: str,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_output_tokens},
    }
    data = _post_json(
        f"{base_url.rstrip('/')}/api/generate",
        payload,
        timeout=timeout,
        headers={},
    )
    text = data.get("response", "")
    if not isinstance(text, str) or not text.strip():
        raise AIProviderError("Ollama response did not contain text output.")
    return text


def extract_openai_text(data: dict) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _post_json(
    url: str,
    payload: dict,
    *,
    timeout: float,
    headers: dict[str, str],
) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **headers,
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AIProviderError(f"HTTP {exc.code} from {url}: {body}") from exc
    except URLError as exc:
        raise AIProviderError(f"Could not connect to {url}: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"Invalid JSON response from {url}: {body[:500]}") from exc

    if not isinstance(data, dict):
        raise AIProviderError(f"Unexpected JSON response from {url}.")
    return data
