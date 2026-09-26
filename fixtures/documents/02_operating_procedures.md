# Starlight Queue operating procedures

This is a fictional document for RAG Playground development and testing.
Document revision 2026-09-03.

## Authentication clock errors

NEBULA-42 means that the client's clock differs from the service clock by more than 120 seconds.

To resolve a clock error, synchronize the client clock with a trusted time source and retry the request with a newly generated timestamp.

Rotating an API key is not the prescribed fix for a clock error. Persistent errors after clock synchronization should be escalated with the request ID and observed clock offset.

## Transient delivery failures

The example Starlight consumer retries HTTP 429 and 503 responses up to three times, with exponential backoff. These are fictional service instructions and do not configure the RAG Playground's own retry policy.

## Consumer recovery

After a consumer restarts, it resumes from the last acknowledged event. Because delivery is at least once, it may see an event again and should deduplicate by event_id.
