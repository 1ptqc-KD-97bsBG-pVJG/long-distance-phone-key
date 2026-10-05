# Working in this repository

This is an experimental, owner-authorized remote phone-key enrollment tool.
Read README.md and docs/browser-endpoint.md before changing the transport.

- Keep the hardware-verified laptop path working. Browser vehicle BLE and Bluefy
  are unverified until actual hardware tests establish otherwise.
- Run `.venv/bin/pytest -q` and `node scripts/test_web_transport.mjs` for transport
  changes. Tests use simulated vehicles; no real-car commands are necessary.
- Do not run echo fixtures or arbitrary payload probes against a physical Tesla.
  `probe` must continue refusing physical backends.
- Use isolated mobile emulator instances and pinned agent-device sessions. Never
  wipe, stop, install onto, or redirect ports on another agent's devices.
- Do not commit VINs, addresses, hostnames, account details, tokens, screenshots,
  APKs, analysis artifacts, or session logs. Artifacts belong in ignored local
  storage. Public examples must use explicit placeholders or synthetic values.
- Preserve loopback-only network binding, explicit host approval, origin checks,
  independent session secrets, bounded queues, and disconnect/expiry cleanup.
- Do not describe an opaque relay as technically enrollment-only. It forwards
  authenticated messages and is intended to run for a short, deliberate session.
- Tailscale configuration is user-owned. Do not reset existing Serve/Funnel
  configurations, publish endpoints, or change network access policy as part of
  routine local tests.
- For real-car work, confirm the target and use a discovery/subscription diagnostic
  before enrollment. Record app and vehicle key-list evidence separately from
  direct entry/driving checks. Stop forwarding after completion.

Source map: Python framing/wire/server implement the local transport;
backends.py contains native car endpoints; web_server.py and web/ implement the
self-hosted browser endpoint; mac/PhoneKeyProxy.swift is the phone-facing BLE
peripheral. Tests and scripts separate simulated transport from hardware checks.
