def extract_memory(text):
    lowered = text.lower()
    triggers = ("remember", "prefer", "always", "never", "avoid", "stick to", "keeps me")
    if any(trigger in lowered for trigger in triggers):
        return {"fact": text.strip(), "evidence": text.strip()}
    return None
