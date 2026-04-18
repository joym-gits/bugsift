# Security Policy

## Supported versions

bugsift is pre-1.0. Only the `main` branch is supported. No backports.

## Reporting a vulnerability

**Do not file security issues in the public tracker.**

Email the maintainer with `[bugsift-security]` in the subject line. Include:

- A description of the vulnerability.
- Reproduction steps or a proof of concept.
- The commit SHA or version where you observed the issue.
- Your assessment of impact (data exposure, RCE, etc.).

You should expect an acknowledgement within 72 hours. We will work with you on
a disclosure timeline; the default is a 90-day embargo from initial report,
shortened if a fix ships sooner.

## Scope

In scope:

- Authentication and authorization flaws (GitHub OAuth, session handling).
- Webhook signature bypass.
- Sandbox escape in the reproduction runner (see §5.5 of the project brief).
- Encryption weaknesses for stored API keys.
- SQL injection, SSRF, or other OWASP top-10 issues in the backend.
- Secrets exposure in logs or API responses.

Out of scope:

- Issues requiring a compromised LLM provider or compromised GitHub.
- Social-engineering attacks against maintainers.
- Denial-of-service via resource exhaustion that requires authenticated abuse
  and is already rate-limited by the documented webhook limits.

## Known sensitive surfaces

- `repro/sandbox.py` is the most security-critical module. It enforces the
  constraints in §5.5 of the project brief: read-only root filesystem,
  writable `/tmp` tmpfs only, all Linux capabilities dropped,
  `no-new-privileges`, `pids-limit=50`, `memory=512m`, `cpus=1`, hard 60s
  wall-clock timeout, ephemeral (`--rm`). **Known follow-up:** the
  "`--network none` + whitelisted egress proxy to PyPI/npm only" part of
  §5.5 is not yet implemented; v1 uses the default bridge network so scripts
  can `pip install` a single dependency at runtime. Tracked as follow-up.
- The worker container has `/var/run/docker.sock` mounted. This is
  equivalent to root on the host — treat the worker image accordingly and
  don't run untrusted code in the same container.
- `security/crypto.py` owns API-key-at-rest encryption and must never log or
  return plaintext keys outside the decrypt path used at LLM call time.
- `github/webhooks.py` verifies `X-Hub-Signature-256` on every incoming event.
