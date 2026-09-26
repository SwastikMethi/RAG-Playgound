# Starlight Queue product guide

This is a fictional document for RAG Playground development and testing.
Document revision 2026-09-02.

## Plans

The Starter plan accepts up to 1,000 events per minute. The Pro plan accepts up to 10,000 events per minute. The plan limits apply separately to each workspace.

| Plan | Event rate | Concurrent consumers |
| --- | --- | --- |
| Starter | 1,000 per minute | 2 |
| Pro | 10,000 per minute | 20 |

Starter event retention is 72 hours. Pro retention changed in September 2026; consult the release notes for the effective date and current duration.

## Delivery

Starlight Queue uses at-least-once delivery. Consumers must use the event_id field to detect duplicate deliveries. A delivery acknowledgment confirms consumption, not completion of the customer's business workflow.

## Support

Business-hours support is available on Starter. Pro includes a one-hour initial response target for severity-one incidents. No annual plan price is specified in this guide.
