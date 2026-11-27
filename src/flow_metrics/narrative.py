"""Narrative layer: turns a FlowReport into prose.

Guardrails:
- The LLM receives only the fact sheet (pre-computed numbers), never raw data.
- The prompt forbids new numbers; `validate_narrative` rejects any number in
  the output that is not present in the fact sheet.
- Without an API key, a deterministic template is used (no LLM at all).
"""

from __future__ import annotations

import json
import os
import re

from .metrics import FlowReport

SYSTEM_PROMPT = """Você é um analista de fluxo ágil. Escreva uma análise curta (até 180 palavras),
em português, para um gestor. Regras:
1. Use SOMENTE os números do fato JSON fornecido. Não calcule, não estime, não arredonde de outra forma.
2. Destaque: previsibilidade (lead time P85), eficiência de fluxo, gargalo e retrabalho.
3. Termine com UMA recomendação prática ligada ao gargalo.
4. Se um dado for null, diga que não está disponível."""


def fact_sheet(report: FlowReport, forecast: dict | None = None, backlog: int | None = None) -> dict:
    """Rounded, LLM-ready facts. Rounding happens here, in code, once."""
    r = report

    def rd(x, n=1):
        if x is None:
            return None
        return int(round(x)) if n == 0 else round(x, n)

    facts = {
        "itens_analisados": r.n_issues,
        "itens_concluidos": r.n_done,
        "lead_time_p50_dias": rd(r.lead_time_p50),
        "lead_time_p85_dias": rd(r.lead_time_p85),
        "cycle_time_p85_dias": rd(r.cycle_time_p85),
        "eficiencia_fluxo_pct": rd(r.flow_efficiency * 100 if r.flow_efficiency is not None else None, 0),
        "throughput_medio_semana": rd(r.throughput_avg),
        "wip_atual": r.wip,
        "retrabalho_pct": rd(r.rework_rate * 100, 0),
        "gargalo_status": r.bottleneck_status,
        "gargalo_media_dias": rd(r.bottleneck_mean_days),
    }
    if forecast and backlog is not None:
        facts["backlog_itens"] = backlog
        facts["previsao_semanas"] = forecast
    return facts


def template_narrative(facts: dict) -> str:
    f = facts
    eff = f["eficiencia_fluxo_pct"]
    text = (
        f"Foram analisados {f['itens_analisados']} itens, dos quais {f['itens_concluidos']} foram concluídos. "
        f"Em 85% dos casos a entrega acontece em até {f['lead_time_p85_dias']} dias (mediana de {f['lead_time_p50_dias']} dias). "
        f"A eficiência de fluxo é de {eff}%: "
        f"{'a maior parte do tempo os itens estão parados esperando' if eff is not None and eff < 50 else 'o trabalho flui com pouca espera'}. "
        f"O maior gargalo é '{f['gargalo_status']}', com média de {f['gargalo_media_dias']} dias por item, "
        f"e o retrabalho atinge {f['retrabalho_pct']}% dos itens. "
    )
    if "previsao_semanas" in f:
        p = f["previsao_semanas"]
        text += (
            f"Para os {f['backlog_itens']} itens do backlog, a previsão é de {p['p50']} semanas (P50) "
            f"a {p['p85']} semanas (P85). "
        )
    text += f"Recomendação: atacar a fila em '{f['gargalo_status']}' antes de puxar trabalho novo."
    return text


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers_in(obj) -> set[str]:
    return {m.replace(",", ".") for m in _NUM.findall(json.dumps(obj, ensure_ascii=False))}


def validate_narrative(text: str, facts: dict) -> list[str]:
    """Return numbers in `text` that do not exist in `facts` (should be empty).

    Small integers (<=10) are allowed: they show up as counts in prose ("3 ações").
    """
    allowed = _numbers_in(facts)
    bad = []
    for n in _NUM.findall(text):
        norm = n.replace(",", ".")
        if norm in allowed:
            continue
        try:
            if float(norm) <= 10 and float(norm).is_integer():
                continue
        except ValueError:
            pass
        bad.append(n)
    return bad


def llm_narrative(facts: dict, model: str = "claude-sonnet-4-5") -> str:
    """Call Claude with the fact sheet only. Falls back to the template if no key."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return template_narrative(facts)
    import anthropic  # optional dependency

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.getenv("FLOW_METRICS_MODEL", model),
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(facts, ensure_ascii=False)}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    bad = validate_narrative(text, facts)
    if bad:
        # Guardrail: never publish invented numbers. Fall back to the template.
        return template_narrative(facts) + f"\n\n[aviso: narrativa do LLM descartada; números fora do fato: {bad}]"
    return text
