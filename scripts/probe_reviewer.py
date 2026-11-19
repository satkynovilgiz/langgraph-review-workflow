"""Sanity check: can the reviewer reject a draft that is clearly bad?

If every real draft gets 5/5/5/5/5, either the drafts are great or the
reviewer is a rubber stamp. Feeding it a draft with KNOWN problems tells
us which. The draft below is in the length range (so the code length
check passes) but has:
  - a factual error (says HTTPS sends the server's PRIVATE key to the browser)
  - unexplained jargon (TLS, cipher suite, ECDHE, AEAD, X.509, PKI...)
  - no concrete example

Run:  python scripts/probe_reviewer.py   (needs GOOGLE_API_KEY, 1 API call)
"""

import json

from workflow.llm import get_llm
from workflow.nodes import make_nodes

BAD_DRAFT = """# How HTTPS Works

HTTPS is HTTP over TLS. When a client connects, it performs a TLS handshake in which
the endpoints negotiate a cipher suite, typically ECDHE with an AEAD cipher such as
AES-GCM or ChaCha20-Poly1305. The server presents its X.509 certificate, which chains
to a root in the client's trust store as part of the PKI.

During the handshake, the server sends its private key to the browser so the browser
can encrypt traffic that only the server can read. This private key is then used for
the rest of the session as the symmetric key, which is why HTTPS is so fast.

## Integrity

Records are protected with an AEAD construction, so any tampering with ciphertext is
detected and the connection is torn down. Sequence numbers prevent replay. Forward
secrecy comes from the ephemeral key exchange, so compromise of long-term keys does not
expose past sessions, assuming the ephemeral secrets were erased.

## Authentication

The certificate binds a public key to a hostname via the SAN extension. Clients check
the signature chain, validity period, and revocation status via OCSP or CRLs. HSTS
headers instruct the client to refuse plain HTTP for a max-age, and certificate
transparency logs make mis-issuance publicly auditable. Pinning is mostly deprecated.

## Versions

TLS 1.0 and 1.1 are deprecated. TLS 1.2 is widely deployed, and TLS 1.3 removes legacy
features such as static RSA key exchange and renegotiation, reduces the handshake to one
round trip, and supports 0-RTT resumption with replay caveats. Middleboxes historically
caused ossification problems, which is why TLS 1.3 disguises itself as TLS 1.2 on the
wire in some fields. QUIC integrates TLS 1.3 directly into the transport layer and is the
basis of HTTP/3, which runs over UDP rather than TCP.

## Performance

Session resumption via tickets or PSKs avoids repeating the full handshake. OCSP
stapling removes a round trip to the CA. With modern hardware AES-NI instructions, the
symmetric encryption overhead is negligible for most workloads, and the main cost is
handshake latency, which TLS 1.3 and connection reuse largely address.

## Summary

HTTPS combines a key exchange, certificates, and AEAD ciphers to give confidentiality,
integrity, and authentication for web traffic.
"""


def main() -> None:
    reviewer = make_nodes(get_llm())["reviewer"]
    update = reviewer({
        "topic": "Explain how HTTPS keeps data safe for beginners",
        "draft": BAD_DRAFT,
        "revision_count": 0,
    })
    print(json.dumps(update["history"][0], indent=2))


if __name__ == "__main__":
    main()
