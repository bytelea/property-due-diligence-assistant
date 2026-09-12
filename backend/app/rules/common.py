"""Pure helpers shared by deterministic rules. No model or network dependencies."""

import re
from uuid import NAMESPACE_URL, uuid5

from app.models.assessment import Evidence
from app.models.property_fact import PropertyFact


def stable_id(rule: str, facts: list[PropertyFact]) -> str:
    return str(uuid5(NAMESPACE_URL, rule + ":" + ":".join(sorted(f.fact_id for f in facts))))


def evidence_links(facts: list[PropertyFact]) -> list[Evidence]:
    return [Evidence(
        source=f"{f.document_type.value}: {f.document_id}", excerpt=f.evidence,
        page=f.page, fact_id=f.fact_id, document_id=f.document_id,
        document_type=f.document_type.value,
    ) for f in sorted(facts, key=lambda f: f.fact_id)]


def matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def documented_number(fact: PropertyFact) -> bool:
    for token in re.findall(r"\d+(?:[., \u00a0]\d+)*", fact.evidence):
        token = token.replace(" ", "").replace("\u00a0", "")
        candidates = {token.replace(",", ".")}
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
            candidates.add(token.replace(",", "").replace(".", ""))
        if "." in token and "," in token:
            decimal = "." if token.rfind(".") > token.rfind(",") else ","
            thousands = "," if decimal == "." else "."
            candidates.add(token.replace(thousands, "").replace(decimal, "."))
        for value in candidates:
            try:
                if float(value) == fact.value:
                    return True
            except ValueError:
                pass
    return False
