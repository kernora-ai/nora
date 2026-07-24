# Verify zero egress

Nora is local-first. On Free / Lite: **0 bytes to Kernora servers**. Telemetry is off by default on every tier (v2.8).

From a terminal:

```bash
kernora network-check
```

That AST-audits hot-path modules for networking primitives outside the allowlist and exits non-zero if a leak is found. You can also run `tcpdump` yourself during a session.

Pro+ adds opt-in sync to **your** S3 (your bucket, your keys) — off by default.

More: [kernora.ai/security](https://kernora.ai/security.html)
