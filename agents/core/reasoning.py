"""LLM gerekçe üretimi — Claude Haiku birincil, kural tabanlı fallback."""
import json
import os
from typing import Optional

from .models import Signal
from .scoring import ScoreResult

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


_SYSTEM_PROMPT = """Sen kırmızı mercimek tedarik riski analistinin asistanısın.
Sana verilen sinyal verilerini (z-skorlar, kaynak URL'leri, notlar) kullanarak
kısa, net ve kaynaklı bir gerekçe üret.

KURALLAR:
1. Yalnızca verilen sinyallere dayan. Uydurma kaynak = ciddi hata.
2. cited_sources listesi yalnızca source_url değerlerini içersin.
3. Öneri (recommendation) her zaman kural motorundan gelir — sen sadece gerekçeyi üretirsin.
4. Türkçe yaz. Maksimum 3 cümle.

Çıktı JSON formatı:
{
  "rationale": "...",
  "key_factors": ["...", "..."],
  "cited_sources": ["url1", "url2"]
}"""


def _build_prompt(result: ScoreResult, signals: list[Signal]) -> str:
    sig_lines = []
    for s in result.top_signals[:3]:
        sig_lines.append(
            f"- [{s.category}/{s.origin}] z={s.anomaly_z:+.2f} | {s.note} | {s.source_url}"
        )
    signals_text = "\n".join(sig_lines) if sig_lines else "(sinyal yok)"
    return (
        f"Origin: {result.origin} | Ufuk: {result.horizon} | "
        f"Risk skoru: {result.score}/100 | Güven: {result.confidence}\n\n"
        f"Top sinyaller:\n{signals_text}\n\n"
        f"Karar önerisi (kural motoru): {result.recommendation}"
    )


def _fallback_rationale(result: ScoreResult) -> dict:
    """LLM erişilemez olursa kural tabanlı gerekçe."""
    if result.score >= 70:
        rationale = (
            f"{result.origin} origin için {result.horizon} ufkunda risk skoru {result.score}/100 — "
            "yüksek. Fiyat ve/veya arz baskısı sinyalleri belirgin."
        )
    elif result.score >= 50:
        rationale = (
            f"{result.origin} origin için {result.horizon} ufkunda risk skoru {result.score}/100 — "
            "orta. Bazı sinyal kategorilerinde dikkat çekici hareketler var."
        )
    else:
        rationale = (
            f"{result.origin} origin için {result.horizon} ufkunda risk skoru {result.score}/100 — "
            "düşük. Mevcut sinyaller belirgin bir tehdit işaret etmiyor."
        )
    cited = list({s.source_url for s in result.top_signals if s.source_url})
    return {
        "rationale": rationale,
        "key_factors": [s.note for s in result.top_signals[:2] if s.note],
        "cited_sources": cited,
    }


def generate_rationale(
    result: ScoreResult,
    signals: list[Signal],
    api_key: Optional[str] = None,
) -> dict:
    """
    ScoreResult + sinyaller → {rationale, recommendation, key_factors, cited_sources}
    Önce Claude Haiku, başarısız olursa GPT-4o-mini, sonra kural tabanlı fallback.
    """
    prompt = _build_prompt(result, signals)
    anthropic_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if _OPENAI_AVAILABLE and openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            data = json.loads(resp.choices[0].message.content)
            data["recommendation"] = result.recommendation
            return data
        except Exception:
            pass  # fallback'e düş

    if _ANTHROPIC_AVAILABLE and anthropic_key:
        try:
            client = anthropic.Anthropic(api_key=anthropic_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                temperature=0.1,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            data["recommendation"] = result.recommendation
            return data
        except Exception:
            pass

    fallback = _fallback_rationale(result)
    fallback["recommendation"] = result.recommendation
    return fallback
