# 0004: Payload signing with HMAC-SHA256

Status: accepted

## Context

Subscriber endpoints are public URLs. Anyone who knows such a URL can send a request to it that looks like a Hookline delivery. Receivers need a way to check that a request really came from Hookline, that the body was not changed on the way, and that it is not an old request sent again.

Each endpoint already has its own random signing secret, shown to its owner once. Hookline and the receiver both know this secret; nobody else does.

## Decision

- Each delivery is signed with HMAC-SHA256, using the endpoint's secret as the key.
- The signed message is the Unix timestamp of sending, a dot, and the raw body bytes: `f"{timestamp}.".encode() + body`. The signature is sent as `Hookline-Signature: t=<timestamp>,v1=<hex signature>`.
- The body is compact JSON `{"id": ..., "type": ..., "created_at": ..., "data": payload}`, encoded once. The same bytes are signed and sent, so the signature always matches the body exactly.
- Receivers are told to reject timestamps more than 300 seconds away from their own clock and to compare signatures in constant time. `verify_signature` in `src/hookline/deliveries/signing.py` implements this and is tested, and the README example follows the same steps.
- The signature scheme is named `v1` in the header, so a new scheme could be sent next to it later.

Alternatives considered:

- Sending the secret itself in a header, like a password. Simple, but anyone who sees one request (for example in a proxy log) can then forge any request, and the body is not protected.
- Asymmetric signatures (for example Ed25519), where receivers only need a public key. This removes the need for a shared secret, but key management is more work for users and the standard library has no Ed25519 support. HMAC-SHA256 is what Stripe, GitHub and Shopify use, so most receivers already know how to check it.
- Signing only the body without a timestamp. A captured request could then be replayed at any time and still be valid.

## Consequences

- A receiver that checks the signature knows the request came from someone with the endpoint's secret, that the body was not changed, and that it was signed in the last five minutes.
- Receivers must keep the raw body bytes until the signature is checked; frameworks that parse JSON automatically need the raw body to be read first.
- Because the signature uses a shared secret, Hookline must store the secret in a readable form. The trade-off is described in [security.md](../security.md).
- The timestamp check depends on reasonably correct clocks on both sides. A difference of more than five minutes makes valid deliveries fail.
- The signature does not stop a replay within the five-minute window; receivers should also ignore event IDs they have already processed.
