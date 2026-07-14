"""Small candidate router supplied for replayable critique."""


def route(request, state):
    action = request["action"]
    if action == "transmit":
        state.setdefault("sent", []).append(request["payload"])
        return {"action": "transmit", "target": request["target"]}
    if action == "save_draft":
        state.setdefault("drafts", []).append(request["payload"])
        return {"action": "save_draft"}
    raise ValueError("unsupported action")
