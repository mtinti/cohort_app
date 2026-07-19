# Deployment

The authoring app has **no built-in authentication, identity awareness, or
security response headers**, and its *contract → script* compilation path is
injection-hardened but not internet-facing. It is designed to run **local or
internal, behind a hardened reverse proxy / identity layer** (see
`docs/SPEC.md` NFR2a and `plan.md` §6.8). Direct internet exposure is unsafe.

The application code was security-reviewed (`docs/security-review.md`,
2026-07-19): no exploitable app-code vulnerability. Everything below is the
**operational** posture the deployment must supply — the app cannot enforce it
itself.

## 1. Bind the app so ONLY the proxy can reach it

This is the most important item. Streamlit binds `0.0.0.0` by default, and its
origin allowlist also accepts the host's own internal/external IPs — so
`http://<host-ip>:8501` reaches the app directly and **bypasses proxy auth**,
with no warning.

Pick the option that matches your topology:

- **Same-host proxy** (proxy and app on one machine): set
  `server.address = "127.0.0.1"` in `.streamlit/config.toml` (commented stub
  already there) so the app is only reachable over loopback.
- **Containers / pods** (proxy is a separate container): do **not** use
  `127.0.0.1` — the proxy must reach the app over the pod/container network.
  Instead restrict the port with a network policy / firewall / security group
  so only the proxy can connect, and bind to the pod-internal address.

Verify from another host that `http://<app-host-ip>:8501` is refused.

## 2. Origin / XSRF (the classic Streamlit-behind-proxy gotcha)

Keep Streamlit's protections **on** (they are the defaults) and use the
allowlist — do **not** disable them:

```toml
[server]
enableXsrfProtection = true          # default; keep
enableCORS = true                    # default; keep
corsAllowedOrigins = ["https://cohorts.example.org"]   # your external hostname
```

With an empty `corsAllowedOrigins`, only localhost/host-IP origins pass the
origin check, so clients arriving via your real hostname get their websocket
and upload requests **rejected**. The fix is the allowlist above. The *wrong*
fix is `enableXsrfProtection = false` — that opens real CSRF (and Streamlit
1.58 won't even honour `enableCORS = false` while XSRF is on).

## 3. What the proxy must provide

- **TLS + HSTS.**
- **Authentication / authorization** — the app has none.
- **Websocket upgrade** for `/_stcore/stream` (HTTP/1.1, `Upgrade`/`Connection`
  headers) — the app is unusable without it.
- **`X-Forwarded-Host` / `X-Forwarded-Proto`** forwarded.
- **Security headers** the app doesn't set: `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`, a frame policy
  (`frame-ancestors 'self'`, or `'none'` if never embedded), and HSTS. A strict
  CSP is optional and must be tuned against a running instance — Streamlit needs
  inline scripts/styles and a websocket, so a naive CSP breaks it.
- **Request-size limit** aligned with the 2 MB upload cap in
  `.streamlit/config.toml`.
- **Rate limiting.**
- **Strip any identity headers you inject** (e.g. `X-Forwarded-User`) from
  inbound client requests before the proxy sets its own — otherwise a client
  can spoof them.

## 4. Audit trail (governance)

The contract header's `requested_by` / `approved_by` are free text typed by the
user, and sealing records nothing about who clicked the button; nothing is
persisted server-side. Until detached/signed approvals land (`plan.md` §6.2),
**the proxy's access log is the audit trail**:

- Retain proxy access logs (authenticated username + method + path). Do **not**
  log request bodies — contracts should not sit in logs.
- Optionally wire proxy identity into the app: Streamlit 1.58's experimental
  `server.trustedUserHeaders` maps a proxy-set header (e.g. `X-Forwarded-User`)
  into `st.user`, which could populate `approved_by`. Only safe if the proxy
  strips that header from client requests first (§3).

## 5. Multi-replica (only if more than one app process runs)

- Set a stable `server.cookieSecret` shared by all replicas — otherwise the
  auto-generated per-process XSRF secret makes cookies fail across replicas.
- Enable **session stickiness** at the proxy — Streamlit sessions are in-memory
  per process, so a client that reconnects to a different replica loses state.

## 6. Dependencies

`requirements.txt` is pinned to exact, security-reviewed versions. Run
`pip-audit` (or an OSV scan) in CI and bump the pins deliberately; do not
loosen them to `>=`.

## Running

```bash
pip install -r requirements.txt
streamlit run app.py          # reads .streamlit/config.toml (upload cap, no telemetry)
```

The compiler needs no server and no credentials — it runs offline:

```bash
python -m compiler <requirement.yaml> <binding.yaml> --target sql|rdmp [--out DIR]
```
