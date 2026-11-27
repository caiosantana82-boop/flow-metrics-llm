# flow-metrics-llm

**Métricas de fluxo Kanban determinísticas + narrativa por LLM com guardrail.**
O Python calcula, o LLM só escreve. Nenhum número chega ao leitor sem ter saído do motor de cálculo.

```
Jira changelog ──► motor determinístico ──► fato JSON ──► LLM (só redige) ──► validador de números ──► relatório
   (sintético)        (metrics.py)          (arredondado      (Claude, opcional)    (descarta números
                                              uma vez)                               inventados)
```

## Por que esse desenho

Em relatórios de gestão, um LLM que "calcula" lead time ou eficiência gera números plausíveis e errados.
Aqui a responsabilidade é separada:

| Camada | Faz | Não faz |
|---|---|---|
| `metrics.py` | lead/cycle time P50/P85, eficiência de fluxo, throughput, WIP, retrabalho, gargalo, forecast Monte Carlo | chamar LLM |
| `narrative.py` | monta o fato JSON, pede a narrativa, **valida** que todo número do texto existe no fato | calcular |

Sem `ANTHROPIC_API_KEY`, a narrativa usa um template determinístico: o projeto roda 100% offline.

## Regras de cálculo (auditáveis)

- **Lead time:** criação → primeira entrada em `DONE`.
- **Cycle time:** primeira entrada em status `ACTIVE` → `DONE`.
- **Eficiência de fluxo:** `Σ tempo ACTIVE / Σ (ACTIVE + WAIT)`. É razão de somas, não média de percentuais por item (teste dedicado mostra a diferença).
- **Gargalo:** status não terminal com maior tempo médio de permanência.
- **Forecast:** Monte Carlo sobre o throughput semanal histórico → semanas para zerar o backlog (P50/P85/P95).
- **Percentil:** interpolação linear (mesmo método padrão do NumPy).

## Rodando

```bash
pip install -e ".[dev]"          # opcional: ".[llm]" para usar o Claude
pytest -q                        # 9 testes
flow-metrics --issues 120 --backlog 40 --out report.json
```

Saída (dados sintéticos):

```json
{
  "itens_analisados": 120,
  "itens_concluidos": 105,
  "lead_time_p85_dias": 17.3,
  "eficiencia_fluxo_pct": 45,
  "gargalo_status": "Waiting to Test",
  "previsao_semanas": {"p50": 6, "p85": 7, "p95": 7}
}
```

> Foram analisados 120 itens, dos quais 105 foram concluídos. Em 85% dos casos a entrega acontece em até 17.3 dias […] O maior gargalo é 'Waiting to Test' […] Recomendação: atacar a fila em 'Waiting to Test' antes de puxar trabalho novo.

## Estrutura

```
src/flow_metrics/
  synthetic.py   # gerador de issues + changelog no formato da Jira API v3
  metrics.py     # motor determinístico
  narrative.py   # fato JSON, prompt, chamada ao Claude e validador de números
  cli.py
tests/test_metrics.py
```

## Próximos passos

- Conector real `POST /rest/api/3/search/jql` com paginação por `nextPageToken` (substitui `synthetic.py`).
- Mapeamento de status → categoria configurável por time (YAML).

---
Código de referência com **dados 100% sintéticos**; nenhum dado corporativo. Licença MIT.
