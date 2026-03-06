════════════════════════════════════════════════════════════════════════════════
ASTU CONNECT — AUTHENTICATION & AUTHORIZATION DESIGN
Local JWT verification, role model, short-lived tokens, instant ban enforcement
════════════════════════════════════════════════════════════════════════════════

Builds on:  res1 §3.1 (Identity Service bounded context)
            res3 §6.1 (Identity REST API)
            res4 §2 (user.events — user.blocked propagation)
            res6 §6.1 (gateway rate limiting)

Goals:      • Zero network round-trip on the auth hot path (token verify
              must be local — no "call Identity on every request").
            • Role-based authorization with per-service enforcement.
            • Access tokens expire fast (minutes, not days).
            • A banned user is locked out INSTANTLY, not at token expiry.

================================================================================
TABLE OF CONTENTS
================================================================================

  §1  Threat Model & Design Constraints
  §2  Token Architecture — Access + Refresh Pair
  §3  JWT Claims Structure
  §4  Local Verification — How Every Service Checks Tokens Offline
  §5  Key Management & Rotation
  §6  Role Model
  §7  Instant Ban — The Denylist Mechanism
  §8  Token Lifecycle — Every State Transition
  §9  Attack Surface & Mitigations
  §10 Service Integration — What Each Service Implements
  §11 Summary — Decision Record

================================================================================
§1  THREAT MODEL & DESIGN CONSTRAINTS
================================================================================

── 1.1  WHAT WE'RE PROTECTING AGAINST ──────────────────────────────

  ┌────────────────────────────────┬─────────────────────────────────┐
  │ Threat                         │ Must be mitigated by            │
  ├────────────────────────────────┼─────────────────────────────────┤
  │ Stolen access token            │ Short TTL (§2). Denylist for    │
  │ (XSS, device theft, shoulder   │ known-compromised tokens (§7).  │
  │  surfing, malware)             │                                 │
  ├────────────────────────────────┼─────────────────────────────────┤
  │ Stolen refresh token           │ Refresh rotation + reuse        │
  │                                │ detection (§2.3). Bound to      │
  │                                │ device fingerprint.             │
  ├────────────────────────────────┼─────────────────────────────────┤
  │ Banned user keeps using app    │ Denylist checked on every       │
  │ until their token expires      │ request (§7). Local cache, not  │
  │                                │ a network call.                 │
  ├────────────────────────────────┼─────────────────────────────────┤
  │ Role escalation via token      │ Roles signed into the JWT (§3). │
  │ tampering                      │ Asymmetric signature — services │
  │                                │ can't forge tokens.             │
  ├────────────────────────────────┼─────────────────────────────────┤
  │ Replay after logout            │ Logout adds jti to denylist     │
  │                                │ (§7.4). Token is dead           │
  │                                │ immediately, not at expiry.     │
  ├────────────────────────────────┼─────────────────────────────────┤
  │ Identity Service becomes a     │ Local verification (§4). Zero   │
  │ latency bottleneck / SPOF      │ sync calls to Identity on the   │
  │                                │ request hot path.               │
  ├────────────────────────────────┼─────────────────────────────────┤
  │ Signing key compromise         │ Key rotation with overlap (§5). │
  │                                │ kid in header → revoke one key  │
  │                                │ without invalidating all        │
  │                                │ in-flight tokens.               │
  └────────────────────────────────┴─────────────────────────────────┘

── 1.2  PERFORMANCE CONSTRAINTS ────────────────────────────────────

  From res3 §3 NFRs:
    • API p95 ≤ 250 ms. Auth must add ≤ 5 ms to the request path.
    • 12,000 concurrent users, ~5,000 req/s total across services.
      If every request called Identity → 5,000 req/s on one service
      just for auth. That's a SPOF and a latency tax. Unacceptable.

  Conclusion: token verification MUST happen inside each service
  with zero network I/O in the common case.

── 1.3  THE CENTRAL TENSION ────────────────────────────────────────

  Local verification (fast) means services don't call Identity.
  But if they don't call Identity, how do they know a user was just
  banned?

  ANSWER: Two mechanisms working together.

    1. SHORT-LIVED ACCESS TOKENS (10 minutes).
       Worst case without a denylist: a banned user keeps access
       for ≤ 10 minutes. Shrinks the window but doesn't close it.

    2. DISTRIBUTED DENYLIST (Redis, event-propagated).
       Closes the window to ~1 second. Services check a local
       Redis-backed denylist on every request. Ban → Identity adds
       to denylist → event propagates → all services deny within
       one Kafka consumer cycle (~100ms) + local cache refresh
       (~1s).

  Short TTL is the SAFETY NET. Denylist is the PRIMARY mechanism.
  If the denylist is unreachable, short TTL ensures the damage
  window is bounded. Defense in depth.

================================================================================
§2  TOKEN ARCHITECTURE — ACCESS + REFRESH PAIR
================================================================================

── 2.1  THE TWO-TOKEN PATTERN ──────────────────────────────────────

  ┌──────────────────────┬──────────────────┬──────────────────────┐
  │                      │ ACCESS TOKEN     │ REFRESH TOKEN        │
  ├──────────────────────┼──────────────────┼──────────────────────┤
  │ Purpose              │ Authorize API    │ Obtain new access    │
  │                      │ requests.        │ tokens.              │
  ├──────────────────────┼──────────────────┼──────────────────────┤
  │ Format               │ JWT (stateless,  │ Opaque random        │
  │                      │ self-contained). │ string (stateful,    │
  │                      │                  │ stored server-side). │
  ├──────────────────────┼──────────────────┼──────────────────────┤
  │ TTL                  │ 10 minutes.      │ 30 days (sliding —   │
  │                      │                  │ refreshed on use).   │
  ├──────────────────────┼──────────────────┼──────────────────────┤
  │ Verified by          │ Every service,   │ Identity Service     │
  │                      │ locally, via     │ ONLY. Requires DB    │
  │                      │ signature check. │ lookup.              │
  ├──────────────────────┼──────────────────┼──────────────────────┤
  │ Sent with            │ Every API call   │ Only to              │
  │                      │ (Authorization:  │ POST /v1/auth/refresh│
  │                      │  Bearer <jwt>).  │ (never to other      │
  │                      │                  │  endpoints).         │
  ├──────────────────────┼──────────────────┼──────────────────────┤
  │ Storage (client)     │ Memory (JS       │ HttpOnly, Secure,    │
  │                      │ variable). NOT   │ SameSite=Strict      │
  │                      │ localStorage.    │ cookie.              │
  │                      │ Mobile: Keychain/│ Mobile: Keychain/    │
  │                      │ Keystore.        │ Keystore.            │
  ├──────────────────────┼──────────────────┼──────────────────────┤
  │ Revocation           │ Via denylist     │ Delete server-side   │
  │                      │ (§7).            │ record. Immediate.   │
  └──────────────────────┴──────────────────┴──────────────────────┘

── 2.2  WHY 10 MINUTES FOR ACCESS TOKENS ──────────────────────────

  Too short (1 min): clients hammer /auth/refresh. At 12k users
  each refreshing every minute = 200 refresh req/s. Wasteful, and
  refresh is a DB-backed operation (not free).

  Too long (1 hour): the denylist becomes load-bearing. If Redis
  hiccups, a banned user might slip through for up to an hour.

  10 minutes balances:
    • ~1 refresh per user per 10 min = 20 refresh req/s. Trivial.
    • Denylist failure window capped at 10 min. Acceptable for our
      risk level (this is a campus social app, not a bank).
    • Denylist itself is a Redis SET lookup (~0.3 ms) so the per-
      request cost is negligible; we CAN check it every time.

── 2.3  REFRESH TOKEN ROTATION + REUSE DETECTION ──────────────────

  Every time a refresh token is used, it's invalidated and a NEW
  refresh token is issued. This is ROTATION.

  refresh_tokens table (Identity Postgres):

    CREATE TABLE refresh_tokens (
      token_hash     BYTEA PRIMARY KEY,  -- SHA-256 of the token
      user_id        UUID NOT NULL,
      family_id      UUID NOT NULL,      -- stable across rotations
      device_id      TEXT NOT NULL,      -- client-provided, stable
      created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      expires_at     TIMESTAMPTZ NOT NULL,
      used_at        TIMESTAMPTZ,        -- NULL = still valid
      revoked_at     TIMESTAMPTZ,        -- set on logout/ban
      revoke_reason  TEXT
    );

    CREATE INDEX idx_refresh_user ON refresh_tokens (user_id);
    CREATE INDEX idx_refresh_family ON refresh_tokens (family_id);

  REFRESH FLOW:

    1. Client sends refresh token R1 to POST /v1/auth/refresh.
    2. Identity hashes R1, looks up the row.
    3. Validate:
         • Row exists? No → 401.
         • expires_at > NOW()? No → 401, delete row.
         • revoked_at IS NULL? No → 401.
         • used_at IS NULL? No → REUSE DETECTED, see below.
    4. UPDATE refresh_tokens SET used_at = NOW()
         WHERE token_hash = sha256(R1);
    5. Generate R2 (new refresh token, same family_id, same
       device_id, new expires_at = NOW() + 30 days).
    6. INSERT R2.
    7. Generate new access JWT.
    8. Return { access_token, refresh_token: R2 } to client.

  REUSE DETECTION (step 3, used_at IS NOT NULL):

    If R1 was already used, either:
      (a) The client has a bug and re-sent an old token. Annoying
          but benign.
      (b) R1 was stolen. The thief used it first (got R2). Now the
          legitimate client is trying R1. OR the legitimate client
          used it first, and the thief is now trying R1.

    Either way, we can't tell who's legit. SAFE RESPONSE:

      UPDATE refresh_tokens SET revoked_at = NOW(),
        revoke_reason = 'reuse_detected'
      WHERE family_id = <R1's family>;    ← kill the whole family

    Result: ALL tokens in this chain (R1, R2, any future Rn) are
    dead. Both the thief and the legitimate user are logged out.
    Legitimate user re-authenticates (password). Thief can't.

    Log this event. Alert if reuse_detected rate > baseline
    (might indicate an active attack).

── 2.4  REFRESH TOKEN BINDING ─────────────────────────────────────

  Refresh tokens are bound to a device_id (client-generated UUID,
  stored in device keychain). A refresh request must include the
  same device_id the token was issued for.

  Mismatch → 401 + revoke the family.

  This stops a stolen refresh token from being used on a different
  device. An attacker would need to steal BOTH the refresh token
  AND the device_id — which typically means they have the whole
  device, at which point we've lost anyway (but short access TTL
  limits ongoing damage after the user notices and triggers
  remote logout via §8.5).

================================================================================
§3  JWT CLAIMS STRUCTURE
================================================================================

── 3.1  THE ACCESS TOKEN ──────────────────────────────────────────

  Standard JWT, three base64url parts separated by dots:

    <header>.<payload>.<signature>

  HEADER:

    {
      "alg": "RS256",          ← asymmetric — see §4.2
      "typ": "JWT",
      "kid": "2026-03-key-a"   ← which signing key — see §5
    }

  PAYLOAD (claims):

    {
      "iss": "identity.astuconnect.internal",  ← issuer
      "sub": "user_9f8e7d6c",                  ← user_id
      "aud": "astuconnect-api",                ← intended audience
      "iat": 1772457600,                       ← issued at (epoch)
      "exp": 1772458200,                       ← expires (iat + 600s)
      "jti": "tok_01HRXYZ...",                 ← unique token ID
                                                  (UUIDv7, for
                                                   denylist lookup)
      "roles": ["student"],                    ← §6 — array of
                                                  role strings
      "tv": 3                                  ← token_version,
                                                  see §7.3
    }

── 3.2  CLAIM-BY-CLAIM RATIONALE ──────────────────────────────────

  ┌────────┬────────────────────────────────────────────────────────┐
  │ Claim  │ Why it's here                                          │
  ├────────┼────────────────────────────────────────────────────────┤
  │ iss    │ Validate that the token came from OUR Identity        │
  │        │ service. Reject tokens with any other issuer.          │
  │        │ Defends against token confusion attacks if we ever     │
  │        │ federate with another IdP.                             │
  ├────────┼────────────────────────────────────────────────────────┤
  │ sub    │ The user_id. Every service uses this as the caller     │
  │        │ identity. No separate "who am I" lookup needed.        │
  ├────────┼────────────────────────────────────────────────────────┤
  │ aud    │ This token is for OUR APIs. If someone mints tokens    │
  │        │ for a different purpose with the same key (shouldn't   │
  │        │ happen, but defense in depth), services reject them.   │
  ├────────┼────────────────────────────────────────────────────────┤
  │ iat /  │ iat so we can detect "token issued before key          │
  │ exp    │ rotation cutoff" (§5). exp for TTL enforcement.        │
  │        │ Both required by RFC 7519; we use both.                │
  ├────────┼────────────────────────────────────────────────────────┤
  │ jti    │ Unique per token. This is the KEY WE CHECK AGAINST     │
  │        │ THE DENYLIST (§7). Without jti, we could only deny     │
  │        │ by user_id (coarse). With jti, we can deny a specific  │
  │        │ compromised token while the user's other sessions      │
  │        │ stay alive.                                            │
  ├────────┼────────────────────────────────────────────────────────┤
  │ roles  │ Authorization happens locally (§6). Signing roles      │
  │        │ into the token means services don't need to call       │
  │        │ Identity to ask "is this user an admin?"               │
  │        │ Trade-off: role changes take effect on next refresh    │
  │        │ (≤ 10 min). Acceptable — role changes are rare.        │
  │        │ For INSTANT role downgrade (e.g., demoting a rogue     │
  │        │ moderator), use token_version bump (§7.3).             │
  ├────────┼────────────────────────────────────────────────────────┤
  │ tv     │ token_version. Stored per-user in Identity DB. On      │
  │        │ ban / password change / "log out all devices", we      │
  │        │ increment it. Services reject tokens where             │
  │        │ claim.tv < user's current tv (via denylist cache).     │
  │        │ This is the MASS INVALIDATION mechanism — kills ALL    │
  │        │ of a user's tokens in one shot without enumerating     │
  │        │ jtis. See §7.3.                                        │
  └────────┴────────────────────────────────────────────────────────┘

── 3.3  WHAT'S DELIBERATELY NOT IN THE TOKEN ───────────────────────

  ✗ display_name, email, avatar
    Profile data. Changes often. Belongs in the API response body,
    not the token. Bloats the token (sent on every request) for
    no auth benefit.

  ✗ permissions (granular)
    Roles are coarse-grained and stable. Permissions (e.g., "can
    post in community X") change constantly and depend on context
    (which community). They're authorization-time lookups, not
    token claims.

  ✗ follower_count, any counters
    Obviously not auth-relevant. Including them would be a privacy
    leak (token is sent to every service) AND a staleness trap.

  ✗ IP address binding
    Mobile clients hop IPs constantly (wifi → cellular → different
    wifi). Binding would cause spurious 401s. Not worth it for our
    threat model.

── 3.4  TOKEN SIZE BUDGET ─────────────────────────────────────────

  Header:      ~60 bytes (base64url)
  Payload:     ~220 bytes (the claims above, base64url)
  Signature:   ~340 bytes (RS256 → 256-byte sig → base64url)
  Total:       ~620 bytes

  Sent on every request in the Authorization header. At 5,000 req/s,
  that's ~3 MB/s of token overhead. Negligible.

  We resist the temptation to add more claims. Every claim added
  is bytes × requests/s × forever. Keep it lean.

================================================================================
§4  LOCAL VERIFICATION — HOW EVERY SERVICE CHECKS TOKENS OFFLINE
================================================================================

── 4.1  THE VERIFICATION FUNCTION ─────────────────────────────────

  Every service embeds the same verification middleware. On every
  authenticated request:

    VERIFY(token):
      1. Parse JWT. Extract header.kid.
      2. Fetch public key for kid from local JWKS cache (§4.3).
         Cache miss → fetch JWKS, retry. Still miss → 401.
      3. Verify signature with the public key.
         Fail → 401 "invalid_signature".
      4. Check iss == "identity.astuconnect.internal".
         Fail → 401 "invalid_issuer".
      5. Check aud == "astuconnect-api".
         Fail → 401 "invalid_audience".
      6. Check exp > NOW() (with 30s clock skew tolerance).
         Fail → 401 "token_expired".
      7. Check iat < NOW() + 30s.
         Fail → 401 "token_from_future".
      8. DENYLIST CHECK (§7):
         a. Is jti in denylist? → 401 "token_revoked".
         b. Is claim.tv < denylist.min_tv[sub]? → 401 "session_invalidated".
      9. PASS. Attach claims to request context:
           ctx.user_id = claim.sub
           ctx.roles   = claim.roles
           ctx.jti     = claim.jti

  Steps 1–7 are pure CPU + one in-process cache lookup. No network.
  Step 8 is one Redis round-trip (~0.3 ms) — or zero if we use the
  L1 cache layer (§7.2). Total: < 1 ms.

── 4.2  WHY ASYMMETRIC SIGNING (RS256, not HS256) ─────────────────

  ┌─────────────────────┬───────────────────┬────────────────────────┐
  │                     │ HS256 (symmetric) │ RS256 (asymmetric)     │
  ├─────────────────────┼───────────────────┼────────────────────────┤
  │ Sign with           │ Shared secret.    │ Private key.           │
  │ Verify with         │ Same secret.      │ Public key.            │
  ├─────────────────────┼───────────────────┼────────────────────────┤
  │ Who can mint tokens │ Anyone with the   │ Only Identity (holds   │
  │                     │ secret = every    │ the private key).      │
  │                     │ verifying service.│                        │
  ├─────────────────────┼───────────────────┼────────────────────────┤
  │ Blast radius of a   │ Any service's     │ Only Identity's key    │
  │ key leak            │ secret leak =     │ matters. Services hold │
  │                     │ full token forge. │ public keys — leak is  │
  │                     │                   │ harmless.              │
  ├─────────────────────┼───────────────────┼────────────────────────┤
  │ Verify speed        │ Faster (~5 μs).   │ Slower (~200 μs for    │
  │                     │                   │ RS256). Still          │
  │                     │                   │ negligible.            │
  ├─────────────────────┼───────────────────┼────────────────────────┤
  │ Key distribution    │ Every service     │ Public key via JWKS    │
  │                     │ needs the secret  │ endpoint. No secrets   │
  │                     │ at deploy time.   │ to distribute.         │
  │                     │ Rotation is a     │ Rotation is clean      │
  │                     │ coordinated       │ (§5).                  │
  │                     │ re-deploy.        │                        │
  └─────────────────────┴───────────────────┴────────────────────────┘

  DECISION: RS256.

  We have 7 services. With HS256, a secret leak in ANY service
  (misconfigured env var, log leak, compromised pod) lets an
  attacker mint admin tokens. With RS256, only Identity can mint.
  Identity's private key lives in a Kubernetes Secret mounted
  only into Identity pods, backed by a secrets manager.

  The ~200 μs verify cost × 5,000 req/s = 1 CPU-second/s = ~1 core
  across the whole platform. Negligible.

  (Ed25519 is faster than RS256 and equally secure. We may switch
   when all client JWT libraries support it cleanly. RS256 is the
   safe, universally-supported choice today.)

── 4.3  JWKS — PUBLIC KEY DISTRIBUTION ─────────────────────────────

  Identity Service exposes:

    GET /.well-known/jwks.json

    → { "keys": [
          { "kid": "2026-03-key-a",
            "kty": "RSA", "alg": "RS256", "use": "sig",
            "n": "<base64url-modulus>", "e": "AQAB" },
          { "kid": "2026-01-key-a",
            "kty": "RSA", ... }        ← previous key, still valid
        ]}

  This is a standard JWKS (JSON Web Key Set, RFC 7517).

  EVERY SERVICE caches this locally:

    On startup:         Fetch JWKS. Store in memory.
    On cache miss:      Token has a kid we don't recognize
                        (new key rotated in). Re-fetch JWKS once.
                        If kid still not found → 401.
    Periodic refresh:   Every 1 hour, re-fetch JWKS in the
                        background. Pick up rotations proactively.
    On fetch failure:   Keep using cached JWKS. Identity being
                        briefly unreachable does NOT break
                        verification — we already have the keys.

  This is the ONLY thing services fetch from Identity for auth,
  and it's cached for an hour. Identity could be down for 59
  minutes and every service would keep verifying tokens correctly.

── 4.4  THE ONE PLACE IDENTITY IS CALLED SYNCHRONOUSLY ─────────────

  POST /v1/auth/refresh — to swap a refresh token for a new access
  token. This HAS to hit Identity (refresh tokens are stateful,
  stored in Identity's DB). But:

    • Clients call this ~once per 10 minutes, not per request.
      At 12k users → 20 req/s. Tiny.
    • It's not in the hot path of any other API. A slow refresh
      means the user waits ~1s once every 10 minutes. Invisible.
    • If Identity is down, clients keep using their current access
      token until it expires (≤ 10 min). Then they're logged out.
      Annoying, but the app doesn't crash and no other service is
      affected.

================================================================================
§5  KEY MANAGEMENT & ROTATION
================================================================================

── 5.1  KEY LIFECYCLE ──────────────────────────────────────────────

  Identity holds MULTIPLE signing keys at once, each identified by
  kid (key ID). Every JWT header includes the kid it was signed
  with. Verifiers look up the matching public key.

  ┌─────────────────────────────────────────────────────────────────┐
  │                                                                 │
  │   time ────────────────────────────────────────────────►        │
  │                                                                 │
  │   Key A:  ████████████████████████████░░░░░                    │
  │           │            │              │                         │
  │           active       grace          deleted                   │
  │           (signs new   (verifies      (removed from             │
  │            tokens)      old tokens,    JWKS)                    │
  │                         no new                                  │
  │                         signing)                                │
  │                                                                 │
  │   Key B:                    █████████████████████████░░░░░     │
  │                             │                                   │
  │                             active (takes over signing)         │
  │                                                                 │
  │   Overlap window = 1 access token TTL (10 min) + buffer         │
  │   → 20 minutes. Any token signed by Key A during its            │
  │   active period will expire before Key A leaves the JWKS.       │
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

── 5.2  ROTATION PROCEDURE ────────────────────────────────────────

  Every 90 days (or immediately on suspected compromise):

    1. Generate Key B (2048-bit RSA, or 3072 if policy tightens).
       kid = "2026-06-key-a" (date-based, human-readable).

    2. Add Key B's public key to the JWKS. Identity now serves
       BOTH keys in /.well-known/jwks.json.

    3. Wait ≥ 1 hour (service JWKS cache refresh interval).
       Now every service has Key B's public key cached.

    4. Switch Identity to sign NEW tokens with Key B.
       Key A enters grace period — still in JWKS, still verifies,
       no longer signs.

    5. Wait ≥ 20 minutes (access TTL + buffer).
       All tokens signed by Key A have now expired naturally.

    6. Remove Key A from JWKS. Delete private key from secrets
       manager.

  During steps 2–5, both keys are valid for verification. Zero
  downtime, zero failed verifications.

── 5.3  EMERGENCY ROTATION (key compromise) ───────────────────────

  If Key A's private key is known or suspected compromised:

    1. Generate Key B. Add to JWKS. (Steps 1–2 above.)

    2. DO NOT wait an hour. Force JWKS refresh:
       Every service exposes POST /internal/auth/refresh-jwks
       (internal-only, mTLS). Ops script calls it on every pod.

    3. Switch signing to Key B immediately.

    4. Add ALL jtis signed by Key A to the denylist? No — too
       many (every active session). INSTEAD:
       Increment EVERY user's token_version (§7.3). This
       invalidates every token system-wide. Mass logout. Users
       re-authenticate. Painful but safe.

    5. Remove Key A from JWKS immediately. Any token signed by
       Key A now fails signature verification (kid not found).

    6. Post-mortem: how was the key compromised? Fix root cause.

  Emergency rotation = ~30 seconds of 401s while JWKS propagates,
  then everyone re-logs-in. Better than an attacker minting admin
  tokens.

── 5.4  KEY STORAGE ───────────────────────────────────────────────

  Private keys: Kubernetes Secret, mounted as a file into Identity
  pods ONLY. Secret backed by external secrets manager (Vault /
  cloud KMS). Access audited. Rotation updates the Secret; Identity
  hot-reloads (watches the mounted file).

  Public keys: Not secret. Served from /.well-known/jwks.json.
  Also checked into the Identity service's config repo (for
  disaster recovery — if Identity's DB and secrets manager both
  die, we can still reconstruct the JWKS).

================================================================================
§6  ROLE MODEL
================================================================================

── 6.1  THE ROLES ──────────────────────────────────────────────────

  ┌──────────────────┬──────────────────────────────────────────────┐
  │ Role             │ Grants                                       │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ student          │ Default. Post, comment, react, follow, chat, │
  │                  │ create communities, join public communities. │
  │                  │ Every verified user has this.                │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ staff            │ Same as student + can create "official"      │
  │                  │ communities (badge), post announcements that │
  │                  │ show in a pinned slot.                       │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ moderator        │ Delete any post/comment (soft delete with    │
  │                  │ audit log). Suspend users (temp ban).        │
  │                  │ View moderation queue (reported content).    │
  │                  │ Cannot: permanently ban, change roles,       │
  │                  │ access system settings.                      │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ admin            │ Everything. Permanent bans. Role assignment. │
  │                  │ System settings. View audit logs. Usually    │
  │                  │ 2–3 people total.                            │
  ├──────────────────┼──────────────────────────────────────────────┤
  │ service          │ INTERNAL ONLY. For service-to-service calls  │
  │                  │ (Feed calling Identity gRPC). Never issued   │
  │                  │ to a human. Separate signing key. See §6.4.  │
  └──────────────────┴──────────────────────────────────────────────┘

  A user holds an ARRAY of roles. Most users: ["student"]. A staff
  moderator: ["student","staff","moderator"]. We don't use a
  hierarchy — roles are additive sets. Simpler to reason about;
  "moderator implies student" is encoded by giving moderators both.

── 6.2  AUTHORIZATION ENFORCEMENT — WHERE IT HAPPENS ───────────────

  TWO LAYERS:

  LAYER 1 — Gateway (coarse)

    Route-level role check. The gateway's route table includes
    a `required_roles` field per route:

      /v1/moderation/*     → requires: ["moderator","admin"]
      /v1/admin/*          → requires: ["admin"]
      /v1/feed/*           → requires: ["student","staff",
                                        "moderator","admin"]
      /v1/auth/*           → requires: []  (unauthenticated)

    Gateway verifies the token (§4.1), extracts roles, checks
    intersection with required_roles. Empty intersection → 403.

    This is the FIRST LINE OF DEFENSE. Keeps obviously-unauthorized
    requests from even reaching the backend.

  LAYER 2 — Service (fine-grained)

    Services RE-VERIFY the token (defense in depth — never trust
    the gateway alone). Then apply business-logic authorization:

      DeletePost use case (Feed Service):
        IF ctx.roles CONTAINS "moderator" OR "admin":
          allow.
        ELIF post.author_id == ctx.user_id:
          allow.
        ELSE:
          403 "not_post_author".

    Role check is one set-contains operation. Instant.

── 6.3  COMMUNITY-SCOPED ROLES (separate from global roles) ───────

  Global roles (in the JWT) are PLATFORM-WIDE. But communities have
  their own moderators who can delete posts IN THAT COMMUNITY ONLY.

  Community roles are NOT in the JWT. They're:
    • Stored in Community Service's DB (community_members table,
      role column).
    • Cached locally in Feed Service (via community.events,
      res4 §2.3 MemberRoleChanged).
    • Checked at authorization time by the service handling the
      request:

        DeleteCommunityPost use case (Community Service):
          community_role = local_cache.get_role(ctx.user_id, community_id)
          IF community_role IN ("moderator","owner"):
            allow.
          ELIF ctx.roles CONTAINS "moderator":  ← global override
            allow.
          ELIF post.author_id == ctx.user_id:
            allow.
          ELSE:
            403.

  Why not in the JWT: A user moderates 50 communities → 50 role
  entries → bloated token. And community roles change frequently
  (owners promoting/demoting) — we don't want to force a refresh
  every time.

── 6.4  SERVICE-TO-SERVICE AUTH (the "service" role) ───────────────

  When Feed Service calls Identity's GetFollowerIds gRPC, that's
  a service-to-service call. No user context. Different token.

  SERVICE TOKENS:
    • Separate signing key (kid: "svc-2026-03-key-a").
    • Claims: { iss, sub: "feed-service", aud, iat, exp, jti,
                roles: ["service"] }
    • TTL: 5 minutes (shorter — services can refresh cheaply).
    • Issued by Identity via a separate internal endpoint:
        POST /internal/auth/service-token
        Auth: mTLS (K8s service mesh client cert identifies
              the calling service).
    • Verified identically (§4.1) but required_roles=["service"]
      on internal gRPC endpoints.

  Why a separate key: If the user-facing key leaks, attackers
  can't mint service tokens (and vice versa). Blast radius
  containment.

  Why not just mTLS for service-to-service: mTLS authenticates
  the SERVICE. The token lets us carry CONTEXT (correlation_id
  in the jti, rate-limit by calling service, audit which service
  called what). Both layers.

================================================================================
§7  INSTANT BAN — THE DENYLIST MECHANISM
================================================================================

── 7.1  THE PROBLEM RESTATED ───────────────────────────────────────

  A banned user holds a valid access token. It's signed correctly,
  not expired, has legitimate roles. Pure stateless verification
  would let it through for up to 10 minutes.

  We need a SMALL piece of shared state that every service checks,
  without turning auth back into a synchronous Identity call.

── 7.2  DENYLIST ARCHITECTURE ─────────────────────────────────────

  Three tiers:

  ┌────────────────────────────────────────────────────────────────┐
  │                                                                │
  │  TIER 1: In-process cache (per-pod, ~5s freshness)            │
  │    • Go: sync.Map or ristretto cache.                         │
  │    • Two structures:                                           │
  │        denied_jtis:   Set<jti>        (individual tokens)     │
  │        min_tv:        Map<user_id→int> (mass invalidation)    │
  │    • Populated from Tier 2 by a background goroutine that     │
  │      polls every 5s (or subscribes to Redis keyspace          │
  │      notifications for instant push).                         │
  │    • VERIFY() step 8 checks this first. Hit → decision in     │
  │      nanoseconds, no network.                                 │
  │                                                                │
  ├────────────────────────────────────────────────────────────────┤
  │                                                                │
  │  TIER 2: Redis (shared, ~100ms freshness)                     │
  │    • Keys:                                                     │
  │        deny:jti:{jti}     → "1"  TTL = token's remaining life │
  │        deny:tv:{user_id}  → <int>  TTL = 30 days (refresh TTL)│
  │    • Written by Identity on ban/logout/password-change.       │
  │    • Read by every service's background refresher.            │
  │    • On Tier 1 cache miss (shouldn't happen normally, but     │
  │      on fresh pod start before first poll), service falls     │
  │      back to a direct Redis EXISTS. ~0.3 ms.                  │
  │                                                                │
  ├────────────────────────────────────────────────────────────────┤
  │                                                                │
  │  TIER 3: Event stream (user.events) — reconciliation          │
  │    • user.banned / user.unbanned events (res4 §2.3).          │
  │    • Consumed by a denylist-sync worker (can be part of each  │
  │      service's event consumer, or a dedicated sidecar).       │
  │    • This is the RECOVERY path: if Redis is wiped, the worker │
  │      replays user.events (compacted topic, res4 §9.2) and     │
  │      rebuilds the deny:tv entries.                            │
  │    • Also the AUDIT path: every ban is durably recorded in    │
  │      Kafka (+ Identity's outbox → Postgres), not just in      │
  │      ephemeral Redis.                                         │
  │                                                                │
  └────────────────────────────────────────────────────────────────┘

── 7.3  THE TOKEN_VERSION TRICK (mass invalidation) ────────────────

  Problem with jti-only denial: when we ban a user, they might
  have 5 active sessions (phone, tablet, two browsers, smart TV).
  We'd need to enumerate and deny 5 jtis. And if we miss one, they
  stay logged in.

  Solution: per-user version counter.

    users table (Identity Postgres):
      ... existing columns ...
      token_version  INT NOT NULL DEFAULT 1

  Every issued JWT includes `"tv": <user.token_version>`.

  To invalidate ALL of a user's tokens:

    1. UPDATE users SET token_version = token_version + 1
         WHERE id = {user_id};
    2. SET deny:tv:{user_id} {new_version} EX 2592000  (30 days)
    3. PUBLISH user.events user.token_invalidated payload

  Every service's VERIFY() step 8b:

    IF claim.tv < denylist.min_tv.get(claim.sub, default=0):
      → 401 "session_invalidated"

  ONE integer increment kills every token for that user, across
  all devices, instantly. No enumeration. No missed sessions.

  WHEN WE BUMP token_version:

    ┌──────────────────────────────┬──────────────────────────────┐
    │ Trigger                      │ Why                          │
    ├──────────────────────────────┼──────────────────────────────┤
    │ Ban (permanent or temporary) │ Banned users must be locked  │
    │                              │ out NOW.                     │
    │ Password change              │ Assume old password was      │
    │                              │ compromised. Kill sessions   │
    │                              │ that might belong to an      │
    │                              │ attacker.                    │
    │ User clicks "log out all     │ Explicit user intent.        │
    │ devices"                     │                              │
    │ Role downgrade               │ A demoted moderator's old    │
    │ (moderator → student)        │ token still says "moderator".│
    │                              │ Bump tv → forces refresh →   │
    │                              │ new token has correct roles. │
    │ Refresh token reuse detected │ Possible theft. Nuke         │
    │ (§2.3)                       │ everything for this user.    │
    └──────────────────────────────┴──────────────────────────────┘

  WHEN WE USE jti DENIAL (single token, not mass):

    • Single-session logout ("log out this device"). We know the
      exact jti from the request context. Deny it, leave other
      sessions alive.
    • Known-compromised token (user reports "I saw a login I
      didn't do"). Deny that session's jti.

── 7.4  BAN FLOW — END TO END ─────────────────────────────────────

  Admin bans user X via POST /v1/admin/users/{X}/ban:

  ┌────────────────────────────────────────────────────────────────┐
  │                                                                │
  │  t=0ms    Admin's request hits Identity Service.               │
  │                                                                │
  │  t=5ms    BanUser use case executes (single DB transaction):   │
  │             UPDATE users SET                                   │
  │               is_banned = true,                                │
  │               banned_at = NOW(),                               │
  │               ban_reason = '...',                              │
  │               token_version = token_version + 1                │
  │             WHERE id = {X};                                    │
  │                                                                │
  │             UPDATE refresh_tokens SET                          │
  │               revoked_at = NOW(),                              │
  │               revoke_reason = 'user_banned'                    │
  │             WHERE user_id = {X} AND revoked_at IS NULL;        │
  │                                                                │
  │             INSERT INTO outbox (...)  -- user.banned event     │
  │             VALUES (..., 'user.banned', {X}, ...);             │
  │                                                                │
  │             COMMIT.                                            │
  │                                                                │
  │  t=8ms    Identity writes to Redis:                            │
  │             SET deny:tv:{X} {new_version} EX 2592000           │
  │                                                                │
  │           (If this Redis write fails — Identity logs it,       │
  │            returns 200 anyway. The outbox event will           │
  │            propagate the ban via Tier 3. Worst case: the       │
  │            ban takes effect in a few seconds via event         │
  │            consumer instead of instantly via Redis.            │
  │            And access token TTL caps it at 10 min.)            │
  │                                                                │
  │  t=10ms   Admin gets 200 OK.                                   │
  │                                                                │
  │  t=10ms   Outbox relay (res4 §7) picks up the outbox row.      │
  │  t=60ms   Publishes user.banned to user.events Kafka topic.    │
  │                                                                │
  │  t=~1s    Every service's denylist background poller runs      │
  │           (5s poll interval, average wait = 2.5s; using        │
  │            keyspace notifications → ~100ms).                   │
  │           Poller reads deny:tv:*, updates Tier 1 cache.        │
  │           min_tv[X] = new_version.                             │
  │                                                                │
  │  t=~1s    User X sends any API request with their old token.   │
  │           VERIFY() step 8b: claim.tv (old) < min_tv[X] (new).  │
  │           → 401 "session_invalidated".                         │
  │                                                                │
  │           Client receives 401, clears local auth state,        │
  │           redirects to login screen.                           │
  │                                                                │
  │           Login attempt → Identity checks is_banned → 403      │
  │           "account_banned" with the ban reason.                │
  │                                                                │
  │           User X is fully locked out. ~1 second after the      │
  │           admin hit "ban".                                     │
  │                                                                │
  └────────────────────────────────────────────────────────────────┘

── 7.5  DENYLIST SIZE & TTL MANAGEMENT ────────────────────────────

  deny:jti:{jti} — TTL = token's remaining life (exp - NOW()).
    Self-cleaning. A denied jti only needs to exist until the
    token would have expired anyway. After that, the token fails
    on `exp` check regardless of denylist.

    Max size: (bans + logouts) per 10 min × 1 entry each.
    At 100 logouts/hour + 1 ban/hour = ~17 entries in the denylist
    at any time. Tiny.

  deny:tv:{user_id} — TTL = 30 days (refresh token TTL).
    After 30 days, all refresh tokens issued before the ban have
    expired anyway. The user can't get a new access token. The
    denylist entry is no longer needed.

    Max size: (bans + password changes + logout-all) per 30 days.
    At ~5 bans/day + ~50 password changes/day + ~20 logout-all/day
    = ~2,250 entries over 30 days. Tiny.

  Total denylist: < 3,000 Redis keys. Fits in L1 cache of every
  pod with room to spare. The 5s poll fetches all entries in one
  SCAN or one SMEMBERS (if we keep an index set).

── 7.6  DENYLIST POLL IMPLEMENTATION ──────────────────────────────

  For efficiency, Identity maintains a Redis SET of active denials:

    deny:index:jti     → Set of all denied jtis
    deny:index:tv      → Set of all user_ids with a bumped tv

  Background poller in each service:

    every 5s:
      pipe = redis.pipeline()
      pipe.SMEMBERS("deny:index:jti")
      pipe.SMEMBERS("deny:index:tv")
      jtis, uids = pipe.execute()

      # Fetch tv values for the uids
      if uids:
        tvs = redis.MGET([f"deny:tv:{u}" for u in uids])
        new_min_tv = dict(zip(uids, [int(t) for t in tvs if t]))
      else:
        new_min_tv = {}

      # Atomic swap of Tier 1 cache
      tier1.denied_jtis = set(jtis)
      tier1.min_tv      = new_min_tv

  One SMEMBERS (~3k members) + one MGET (~2k keys) = ~1 ms of
  Redis work per 5s per pod. At 30 pods: 6 queries/sec total.
  Negligible.

  Cleanup: when deny:jti:{jti} or deny:tv:{u} TTLs out, a
  small reconciliation job (hourly) SREMs stale members from the
  index sets. Or: use Redis keyspace notifications on expiry to
  SREM on the spot.

── 7.7  FAILURE MODES ─────────────────────────────────────────────

  ┌──────────────────────────────┬──────────────────────────────────┐
  │ Failure                      │ Behavior                         │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ Redis unreachable for a pod  │ Tier 1 cache serves stale data   │
  │                              │ (last successful poll). A ban    │
  │                              │ issued during the outage won't   │
  │                              │ reach this pod until Redis       │
  │                              │ recovers.                        │
  │                              │ MITIGATION: fall back to "deny   │
  │                              │ by default if stale > 60s"?      │
  │                              │ → No — too aggressive. Accept    │
  │                              │ the window (capped at 10 min by  │
  │                              │ token TTL). Alert on Redis       │
  │                              │ unreachability so ops fixes it.  │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ Redis wiped (data loss)      │ All deny:* keys gone. Banned     │
  │                              │ users temporarily unblocked.     │
  │                              │ RECOVERY: denylist-sync worker   │
  │                              │ (Tier 3) replays user.events     │
  │                              │ (compacted, res4 §9.2). Every    │
  │                              │ user.banned / user.token_        │
  │                              │ invalidated event is replayed;   │
  │                              │ worker re-SETs deny:tv entries.  │
  │                              │ ~2 min to rebuild (res5 RB-7     │
  │                              │ analog). During that 2 min +     │
  │                              │ ≤ 10 min token TTL = max 12 min  │
  │                              │ exposure. Alert fires;           │
  │                              │ on-call can manually re-ban      │
  │                              │ known bad actors if urgent.      │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ Poller goroutine crashes     │ Tier 1 never refreshes.          │
  │ (bug)                        │ MITIGATION: health check         │
  │                              │ endpoint reports poller last-    │
  │                              │ success-time. K8s liveness probe │
  │                              │ kills the pod if > 60s stale.    │
  │                              │ New pod starts with fresh poll.  │
  ├──────────────────────────────┼──────────────────────────────────┤
  │ Identity's Redis SET on ban  │ Outbox event still fires.        │
  │ fails (Redis was down at     │ Denylist-sync worker consumes    │
  │ exactly the wrong moment)    │ user.banned → SETs deny:tv.      │
  │                              │ Ban takes effect in ~5s instead  │
  │                              │ of ~1s. Still fast.              │
  └──────────────────────────────┴──────────────────────────────────┘

================================================================================
§8  TOKEN LIFECYCLE — EVERY STATE TRANSITION
================================================================================

── 8.1  LOGIN ──────────────────────────────────────────────────────

  POST /v1/auth/login { email, password, device_id }

    Identity:
      1. Look up user by email.
      2. Verify password (bcrypt/argon2id).
      3. IF is_banned → 403 "account_banned" { reason, appeal_url }.
      4. Generate refresh_token (256-bit random).
         INSERT INTO refresh_tokens (...).
      5. Generate access JWT:
           sub = user.id
           roles = user.roles
           tv = user.token_version
           jti = new UUIDv7
           exp = NOW() + 10 min
           Sign with current private key.
      6. Return { access_token, refresh_token, expires_in: 600 }.
         Set refresh_token as HttpOnly cookie (web) or return in
         body (mobile).

── 8.2  AUTHENTICATED REQUEST (the hot path) ──────────────────────

  GET /v1/feed/timeline
    Authorization: Bearer <jwt>

    Gateway: VERIFY(token) per §4.1. Check route roles. Forward.
    Feed Service: VERIFY(token) again. Extract ctx.user_id. Serve.

    No Identity call. No DB call for auth. ~1 ms auth overhead.

── 8.3  REFRESH ────────────────────────────────────────────────────

  POST /v1/auth/refresh
    Cookie: refresh_token=<R1> (web) or body (mobile)
    Header: X-Device-Id: <device_id>

    Identity: per §2.3. Validate R1. Rotate to R2. Issue new JWT.

    Client: replace stored access token. Replace stored refresh
    token with R2.

    Clients refresh PROACTIVELY at ~8 min (before expiry) to avoid
    a 401-then-refresh-then-retry dance. If proactive refresh
    fails, fall back to reactive (on 401).

── 8.4  SINGLE LOGOUT ─────────────────────────────────────────────

  POST /v1/auth/logout
    Authorization: Bearer <jwt>

    Identity:
      1. Extract jti from token. SET deny:jti:{jti} "1" EX <exp-now>.
         SADD deny:index:jti {jti}.
      2. Mark this session's refresh_token row as revoked
         (by family_id from the refresh cookie, or by a
         session_id claim if we add one).
      3. Return 200. Clear refresh cookie.

    Client: discard access token. Redirect to login.

    Other sessions on other devices remain valid.

── 8.5  LOGOUT ALL DEVICES ────────────────────────────────────────

  POST /v1/auth/logout-all
    Authorization: Bearer <jwt>

    Identity:
      1. UPDATE users SET token_version = token_version + 1
           WHERE id = ctx.user_id.
      2. SET deny:tv:{user_id} <new_tv> EX 2592000.
         SADD deny:index:tv {user_id}.
      3. UPDATE refresh_tokens SET revoked_at = NOW()
           WHERE user_id = ctx.user_id AND revoked_at IS NULL.
      4. Emit user.token_invalidated event via outbox.
      5. Return 200.

    All sessions, all devices, dead within ~1s.

── 8.6  BAN (admin action) ─────────────────────────────────────────

  POST /v1/admin/users/{user_id}/ban { reason, duration? }

    Per §7.4. Identical to logout-all plus is_banned flag.

── 8.7  UNBAN ──────────────────────────────────────────────────────

  POST /v1/admin/users/{user_id}/unban

    Identity:
      1. UPDATE users SET is_banned = false, banned_at = NULL.
      2. DEL deny:tv:{user_id}.
         SREM deny:index:tv {user_id}.
      3. Emit user.unbanned via outbox.

    User can now log in again. They'll need to re-authenticate
    (all their old refresh tokens were revoked during ban).

── 8.8  ROLE CHANGE ────────────────────────────────────────────────

  PUT /v1/admin/users/{user_id}/roles { roles: [...] }

    Identity:
      1. UPDATE users SET roles = {new_roles}.
      2. IF new_roles ⊂ old_roles (downgrade):
           Bump token_version (force refresh → new token has
           fewer roles).
         ELSE (upgrade):
           No bump. User picks up new roles on next natural
           refresh (≤ 10 min). An upgrade delayed 10 min is
           fine; a downgrade must be instant.
      3. Emit user.roles_changed via outbox.

================================================================================
§9  ATTACK SURFACE & MITIGATIONS
================================================================================

┌──────────────────────────────┬──────────────────────────────────────────────┐
│ Attack                       │ Mitigation                                   │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Token theft via XSS          │ Access token in memory (JS var), never       │
│                              │ localStorage. Refresh token HttpOnly cookie  │
│                              │ — JS can't read it. CSP headers. Short       │
│                              │ access TTL limits damage.                    │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Token theft via MITM         │ HTTPS everywhere. HSTS. No token in URLs     │
│                              │ (always headers/cookies). Cert pinning on    │
│                              │ mobile.                                      │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ CSRF on refresh endpoint     │ Refresh cookie is SameSite=Strict. Endpoint  │
│                              │ requires X-Device-Id header (simple requests │
│                              │ can't set custom headers cross-origin).      │
│                              │ CORS locked to our origins.                  │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Token replay after logout    │ jti denylist (§7.4). Token dead instantly.   │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Token forge via "alg":"none" │ Verifier REJECTS tokens with alg != RS256.   │
│ or algorithm confusion       │ Never derives the algorithm from the token   │
│                              │ — it's hardcoded in the verifier config.     │
│                              │ Reject "alg":"HS256" attempts (attacker      │
│                              │ using the public key as an HMAC secret).     │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ kid injection (attacker      │ kid is only used as a MAP KEY into our       │
│ points kid at a URL or file) │ JWKS cache. It's a string lookup, not a      │
│                              │ fetch. Unknown kid → 401, period.            │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Refresh token theft          │ Rotation + reuse detection (§2.3). Family    │
│                              │ revocation on reuse. Device binding (§2.4).  │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Brute-force on /auth/login   │ Rate limit: 5 attempts / 15 min / IP, AND    │
│                              │ 10 attempts / hour / account (whichever      │
│                              │ trips first). Exponential backoff on fail.   │
│                              │ CAPTCHA after 3 fails. bcrypt cost = 12.     │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Privilege escalation via     │ Roles are inside the signed payload. Any     │
│ claim tampering              │ edit invalidates the signature. Asymmetric   │
│                              │ keys — only Identity can sign.               │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Signing key exfil from a     │ Private key ONLY in Identity pods. Other     │
│ non-Identity service         │ services hold public keys (harmless if       │
│                              │ leaked). Secrets manager + audit trail.      │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Denial-of-service via        │ Gateway rate limit (res6 §6.1). Expensive    │
│ expensive token verification │ verify (RS256) is ~200 μs — attacker would   │
│                              │ need 5,000 req/s to consume 1 core. Gateway  │
│                              │ sheds at 5,000 req/s route-level ceiling.    │
├──────────────────────────────┼──────────────────────────────────────────────┤
│ Clock skew exploitation      │ 30s tolerance on exp/iat. NTP on all nodes.  │
│ (attacker exploits a service │ Alert if any service's clock drifts > 10s    │
│  with a slow clock)          │ from cluster consensus.                      │
└──────────────────────────────┴──────────────────────────────────────────────┘

================================================================================
§10  SERVICE INTEGRATION — WHAT EACH SERVICE IMPLEMENTS
================================================================================

┌──────────────────┬──────────────────────────────────────────────────────────┐
│ Component        │ Auth responsibilities                                    │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ API Gateway      │ • VERIFY(token) — first line of defense.                 │
│                  │ • Route-level role check (required_roles per route).     │
│                  │ • Rate limit by ctx.user_id (post-auth, so bots can't    │
│                  │   hide behind fake user_ids).                            │
│                  │ • Rejects obviously-bad requests before they hit any     │
│                  │   service.                                               │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ Identity Service │ • Issues tokens (login, refresh, service-token).         │
│                  │ • Holds private signing keys.                            │
│                  │ • Serves /.well-known/jwks.json.                         │
│                  │ • Owns users.token_version and refresh_tokens table.     │
│                  │ • Writes deny:* keys on ban/logout/tv-bump.              │
│                  │ • Emits user.banned / user.token_invalidated events.     │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ Feed Service     │ • VERIFY(token). Re-check roles for moderator actions.   │
│                  │ • Resource-level authz: "is ctx.user_id the post         │
│                  │   author?"                                               │
│                  │ • Community-role check via local cache (for community    │
│                  │   posts).                                                │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ Chat Service     │ • VERIFY(token) on WS upgrade AND on every WS frame      │
│                  │   (token can expire mid-connection — client must send    │
│                  │   a fresh token via {"t":"auth","token":"..."} frame;    │
│                  │   server 401s frames if token expired > grace period).   │
│                  │ • Block-list check (separate from auth — a blocked user  │
│                  │   has a valid token but can't message specific users).   │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ Community Service│ • VERIFY(token). Community-scoped role authz.            │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ Notification Svc │ • Pure Kafka consumer — no inbound HTTP auth.            │
│                  │ • Events carry user_id in the payload; no token needed.  │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ Search Indexer   │ • Same — pure consumer.                                  │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ Media Service    │ • VERIFY(token) on upload.                               │
│                  │ • Download: signed URLs (separate short-lived signature  │
│                  │   in the URL, not the JWT — media URLs may be shared).   │
├──────────────────┼──────────────────────────────────────────────────────────┤
│ ALL HTTP         │ Share the same auth middleware package:                  │
│ services         │   import "astuconnect/pkg/auth"                          │
│                  │   // Provides:                                           │
│                  │   //   auth.Middleware()     → gin/echo/http middleware  │
│                  │   //   auth.RequireRole(...) → role-guard decorator      │
│                  │   //   auth.Context(ctx)     → extract user_id, roles    │
│                  │ One implementation, tested once, used everywhere.        │
└──────────────────┴──────────────────────────────────────────────────────────┘

── 10.1  SHARED AUTH MIDDLEWARE — INTERNALS ───────────────────────

  pkg/auth/
    ├── middleware.go    — HTTP middleware, attaches ctx.
    ├── verify.go        — VERIFY() per §4.1. Pure function.
    ├── jwks.go          — JWKS fetcher + cache. Background refresh.
    ├── denylist.go      — Tier 1 cache + Redis poller (§7.6).
    ├── roles.go         — RequireRole(), HasRole(), HasAnyRole().
    └── service_token.go — Mint + verify service-to-service tokens.

  Initialization in each service's main():

    authCfg := auth.Config{
      JWKSURL:       "http://identity/.well-known/jwks.json",
      Issuer:        "identity.astuconnect.internal",
      Audience:      "astuconnect-api",
      DenylistRedis: redisClient,
      ClockSkew:     30 * time.Second,
    }
    auth.Init(authCfg)   // starts JWKS refresher + denylist poller

    router.Use(auth.Middleware())
    router.POST("/admin/ban", auth.RequireRole("admin"), banHandler)

================================================================================
§11  SUMMARY — DECISION RECORD
================================================================================

┌───────────────────┬────────────────────────────────────────────────────────┐
│ Area              │ Decision                                               │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Token format      │ JWT (RS256) for access, opaque random for refresh.     │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Access TTL        │ 10 minutes. Balances refresh load (20 req/s) vs.       │
│                   │ exposure window (denylist-failure fallback).           │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Refresh TTL       │ 30 days sliding. Rotation on use. Reuse detection      │
│                   │ → revoke whole family. Device-bound.                   │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Verification      │ LOCAL in every service. JWKS cached 1h. Zero sync      │
│                   │ calls to Identity on the request hot path. < 1 ms.     │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Signing           │ RS256 asymmetric. Private key in Identity only.        │
│                   │ Services hold public keys (leak-safe). 90-day          │
│                   │ rotation with 20-min grace overlap. kid in header      │
│                   │ enables zero-downtime rotation.                        │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Roles             │ Array in JWT: student / staff / moderator / admin /    │
│                   │ service. Additive (no hierarchy). Coarse, stable.      │
│                   │ Community-scoped roles are NOT in the token — they're  │
│                   │ service-local state, event-propagated.                 │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Authorization     │ Two-layer: gateway (route-level required_roles) +      │
│                   │ service (resource-level business logic). Defense in    │
│                   │ depth — service re-verifies, never trusts gateway      │
│                   │ blindly.                                               │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Instant ban       │ token_version per user. Ban → increment tv → write     │
│                   │ deny:tv:{user} to Redis → services' background poller  │
│                   │ picks up in ≤ 5s → Tier 1 cache updated → next request │
│                   │ rejected (claim.tv < min_tv). ~1s admin-click-to-      │
│                   │ locked-out. One integer bump kills ALL sessions —      │
│                   │ no enumeration.                                        │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Single logout     │ jti denylist. TTL = token's remaining life (self-      │
│                   │ cleaning). Affects one session, others stay alive.     │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Denylist tiers    │ T1 in-process cache (5s poll, ns lookup) → T2 Redis    │
│                   │ (shared state, ~0.3 ms fallback) → T3 Kafka            │
│                   │ user.events (durable audit + rebuild source).          │
│                   │ ~3k keys total. ~1 MB memory. Negligible.              │
├───────────────────┼────────────────────────────────────────────────────────┤
│ Failure posture   │ Denylist unreachable → stale T1 cache serves; exposure │
│                   │ capped at 10 min by token TTL. Identity down →         │
│                   │ existing tokens keep working (JWKS cached); refresh    │
│                   │ fails gracefully at next 10-min cycle. No auth-        │
│                   │ induced cascading failure.                             │
└───────────────────┴────────────────────────────────────────────────────────┘

  WHY THIS DESIGN IS SOUND

    1. FAST — Verification is local CPU + L1 cache lookup. Sub-
       millisecond. 5,000 req/s adds ~1 core of auth overhead
       across the whole platform. No network chokepoint.

    2. SECURE — Asymmetric signing confines mint capability to
       Identity. Short TTL + denylist + refresh rotation + reuse
       detection = multiple overlapping walls. Compromise of any
       ONE defense doesn't give full access.

    3. INSTANT REVOCATION — The token_version mechanism gives
       O(1) mass invalidation without enumerating sessions. Banned
       user locked out in ~1 second, not 10 minutes.

    4. SELF-HEALING — Denylist TTLs are tied to token TTLs; stale
       entries expire naturally. Redis wipe recovers via Kafka
       replay. Key rotation is zero-downtime. No manual cleanup.

    5. OPERATIONALLY SIMPLE — One shared middleware package. One
       JWKS endpoint. One Redis namespace. Testable in isolation.
       New services get auth "for free" by importing the package.

════════════════════════════════════════════════════════════════════════════════
END
════════════════════════════════════════════════════════════════════════════════
