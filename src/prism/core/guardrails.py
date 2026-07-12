import re
from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_anonymizer import AnonymizerEngine

_nlp_engine = NlpEngineProvider(
    nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }
).create_engine()
_analyzer = AnalyzerEngine(nlp_engine=_nlp_engine)
_anonymizer = AnonymizerEngine()  # type: ignore[no-untyped-call]

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+\w+", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*:", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?(system|instructions|prompt)", re.IGNORECASE),
    re.compile(r"new\s+instructions\s*:", re.IGNORECASE),
]


@dataclass
class GuardrailResult:
    flagged: bool
    reason: str | None
    redacted_text: str


def scan_prompt(text: str) -> GuardrailResult:
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return GuardrailResult(
                flagged=True,
                reason="Potential prompt injection detected",
                redacted_text=text,
            )

    _SENSITIVE_ENTITIES = {
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
        "IBAN_CODE",
        "IP_ADDRESS",
        "US_DRIVER_LICENSE",
        "US_PASSPORT",
        "MEDICAL_LICENSE",
    }
    results = _analyzer.analyze(
        text=text,
        language="en",
        entities=list(_SENSITIVE_ENTITIES),
    )
    if results:
        anonymized = _anonymizer.anonymize(
            text=text,
            analyzer_results=results,  # type: ignore[arg-type]
        )
        return GuardrailResult(
            flagged=True,
            reason=(
                f"PII detected: {', '.join(sorted({r.entity_type for r in results}))}"
            ),
            redacted_text=anonymized.text,
        )

    return GuardrailResult(flagged=False, reason=None, redacted_text=text)
