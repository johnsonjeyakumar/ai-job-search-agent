"""Application execution engine (Phase 7).

The engine turns one APPROVED preparation package into a controlled apply
workflow. It is deliberately NOT ``apply_everywhere()``: every run picks a
platform adapter, resolves a per-platform execution policy, and only performs
actions the policy allows. Everything stops at the human approval boundary
before any external submission.
"""
