"""flow_metrics: deterministic Kanban flow metrics + LLM narrative layer.

Design rule: every number is computed in Python. The LLM only receives a
fact sheet (JSON) and writes prose about it. It never calculates.
"""

__version__ = "0.1.0"
