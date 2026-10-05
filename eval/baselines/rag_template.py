from eval.baselines.direct_llm import DirectLLM


class RAGTemplate(DirectLLM):
    """Deterministic retrieval over visible records + static handoff template.

    Retrieval selects records for observed high-priority planned items and their
    handoff, preserving the full stage chain. Model prediction remains wholly
    delegated to the explicitly labeled provider.
    """

    method = "rag_template"

    def build_request(self, context):
        request = super().build_request(context)
        items = {
            e.payload.get("item_id")
            for e in context.events
            if e.payload.get("stage") == "PLAN"
            and e.payload.get("priority") in {"HIGH", "CRITICAL"}
        }
        selected = [
            e
            for e in context.events
            if e.payload.get("item_id") in items or e.payload.get("stage") == "HANDOFF"
        ]
        request["records"] = [e.model_dump(mode="json") for e in selected]
        request["template"] = {
            "situation": "",
            "background": "",
            "assessment": "",
            "pending_items": [],
            "source_ids": [],
        }
        request["retrieval"] = (
            "visible high-priority item records plus current handoff; no gold evidence"
        )
        return request
