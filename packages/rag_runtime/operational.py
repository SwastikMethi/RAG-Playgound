"""Operational metadata only. Content belongs in the authenticated trace store."""

import json


def log_event(event, **metadata):
    print(json.dumps({"event": event, **metadata}, separators=(",", ":")), flush=True)
