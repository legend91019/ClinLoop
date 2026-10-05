"""Explicit model baselines, independent rules, and the actual worker adapter."""


def make_handler(method: str, provider=None):
    from eval.baselines.clinloop import ClinLoopAdapter
    from eval.baselines.direct_llm import DirectLLM
    from eval.baselines.rag_template import RAGTemplate
    from eval.baselines.rule_engine import RuleEngine

    factories = {
        "direct_llm": lambda: DirectLLM(provider),
        "rag_template": lambda: RAGTemplate(provider),
        "rule_engine": RuleEngine,
        "ClinLoop": ClinLoopAdapter,
    }
    if method not in factories:
        raise ValueError(f"unknown method: {method}")
    return factories[method]()
