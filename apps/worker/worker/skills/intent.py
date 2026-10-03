from __future__ import annotations
from packages.contracts import ClinicalIntent, IntentType, new_id


def extract_clinical_intent(text: str, *, patient_id: str = "UNKNOWN", encounter_id: str = "UNKNOWN", source_event_id: str | None = None) -> ClinicalIntent | None:
    if "血培养" in text or "blood culture" in text.lower():
        return ClinicalIntent(intent_id=new_id("INT"), patient_id=patient_id, encounter_id=encounter_id, intent_type=IntentType.FOLLOW_RESULT, text=text, expected_evidence=["blood_culture_result"], source_event_id=source_event_id)
    return None
