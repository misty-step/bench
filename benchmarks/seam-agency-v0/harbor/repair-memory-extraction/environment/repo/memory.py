"""Memory extraction with a known keyword-seam defect."""


def extract_memory(text):
    lowered = text.lower()
    if "remember" in lowered or "i prefer" in lowered:
        return {"fact": text, "evidence": text}
    return None
