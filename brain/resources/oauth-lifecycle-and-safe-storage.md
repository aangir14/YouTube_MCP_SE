---
title: OAuth 2.0 Lifecycle, Safe Credential Storage, and Least Privilege
author: Aangir Doshi
date: 2026-11-19
type: research-note
status: active
srs_ids:
  - FR-9.1
  - FR-9.2
  - FR-9.3
  - FR-9.4
  - FR-9.5
  - FR-9.6
  - FR-9.7
  - FR-9.8
  - FR-9.9
  - COM-1
  - COM-2
  - COM-3
  - COM-4
  - NFR-SEC
  - TBD-6
  - TBD-7
sources:
  - "https://datatracker.ietf.org/doc/html/rfc7636"
  - "https://datatracker.ietf.org/doc/html/rfc8252"
  - "https://developers.google.com/identity/protocols/oauth2/native-app"
  - "https://developers.google.com/youtube/v3/guides/auth/installed-apps"
evidence:
  - "docs/testing/acceptance-cases.md#sec-oauth"
  - "docs/testing/acceptance-cases.md#sec-secrets"
  - "docs/testing/acceptance-cases.md#neg-auth"
  - "docs/testing/acceptance-cases.md#st-fr9"
uncertainty:
  - "TBD-6: Definitive minimum write scope (youtube vs youtube.force-ssl) required for playlist creation without broad channel-management rights"
  - "TBD-7: Execution timeline and automation for 7-day refresh token renewal prior to scheduled course viva"
  - "Headless Linux CI compatibility for OS keyring without active D-Bus session"
---

# OAuth 2.0 Lifecycle, Safe Credential Storage, and Least Privilege

## 1. OAuth 2.0 Architecture for Native Installed Applications

FocusList runs as a local native subprocess managed by an AI client. To establish authenticated access to the user's personal YouTube data (likes, subscriptions, playlists, channel creation) without compromising user credentials, FocusList implements the **OAuth 2.0 Authorization Code Grant with Proof Key for Code Exchange (PKCE)** per **RFC 7636** and **RFC 8252** (**FR-9.1–FR-9.4**).

```
+-----------------------------------------------------------------------------------+
| FocusList Local CLI (focuslist auth login)                                        |
|  1. Generate cryptographically random code_verifier (32 bytes entropy)            |
|  2. Compute code_challenge = BASE64URL(SHA256(code_verifier))                     |
|  3. Generate random state parameter (CSRF protection)                             |
|  4. Open local ephemeral TCP listener on 127.0.0.1:<PORT>                         |
+-----------------------------------------------------------------------------------+
                                          |
                                          | 5. Launch User's Default Browser
                                          v
+-----------------------------------------------------------------------------------+
| Google Identity Consent Screen                                                    |
|  https://accounts.google.com/o/oauth2/v2/auth                                     |
|  ?client_id=...&redirect_uri=http://127.0.0.1:<PORT>&scope=...                    |
|  &code_challenge=...&code_challenge_method=S256&state=...                         |
+-----------------------------------------------------------------------------------+
                                          |
                                          | 6. User Grants Consent & Browser Redirects
                                          v
+-----------------------------------------------------------------------------------+
| Ephemeral Loopback Listener (127.0.0.1:<PORT>)                                    |
|  - Validate received state matches generated state                                |
|  - Extract authorization code                                                     |
|  - Return clean HTTP 200 "Authorization successful. You may close this window."   |
|  - Terminate socket listener immediately                                          |
+-----------------------------------------------------------------------------------+
                                          |
                                          | 7. POST /token with code + code_verifier
                                          v
+-----------------------------------------------------------------------------------+
| Google Token Endpoint (https://oauth2.googleapis.com/token)                       |
|  - Returns access_token, refresh_token, expires_in, token_type                    |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
| Safe Storage: Tokens stored in OS Credential Store (Keyring / Protected File)     |
+-----------------------------------------------------------------------------------+
```

---

## 2. Ephemeral Loopback Listener Security Controls

Following RFC 8252 Section 7.3:
1. **Loopback Binding**: The listener binds strictly to the loopback interface (`127.0.0.1`). It never binds to `0.0.0.0` or public network interfaces.
2. **Dynamic Ephemeral Port**: The port is assigned dynamically by the operating system (`sock.bind(('127.0.0.1', 0))`), avoiding port conflicts with local software.
3. **State Parameter Verification**: A high-entropy cryptographic nonce is sent with the authorization request and verified on callback. Any callback with a missing or mismatched `state` is rejected with HTTP 400.
4. **Immediate Lifecycle Termination**: The TCP listener accepts exactly one valid HTTP GET callback and closes immediately. It does not linger as a background daemon.

---

## 3. Least-Privilege Incremental Scoping (TBD-6)

FocusList adheres to the principle of least privilege (**NFR-SEC**):
1. **Default Read-Only Phase**: Upon initial login, FocusList requests **only** the read-only scope:
   `https://www.googleapis.com/auth/youtube.readonly`
   This scope suffices for video fact sheets, similarity scoring, recommendations, and engagement analysis (**FR-1 to FR-4**).
2. **Incremental Consent on First Write (TBD-6 / ADR-003)**: Write permission is **not** requested during initial setup. Only when the learner approves their first playlist creation proposal (**FR-5.9**) does FocusList initiate incremental consent for the single additional write scope.
   - *TBD-6 Options under evaluation*:
     - `https://www.googleapis.com/auth/youtube` (Full YouTube management scope; universally supported by Google client libraries).
     - `https://www.googleapis.com/auth/youtube.force-ssl` (Restricted write scope allowing video and playlist edits over SSL).
   - *Resolution target*: ADR-003 in C10 will document and benchmark these options.

---

## 4. Secure Credential Storage and Token Isolation

FocusList enforces strict separation between application state and credential material:
1. **OS Credential Store Primary Storage**: Tokens (`access_token`, `refresh_token`) and proposal HMAC signing keys are persisted using the OS credential store:
   - **Windows**: Windows Credential Manager (`win32cred`).
   - **macOS**: Keychain Services.
   - **Linux**: Secret Service API via `keyring` package.
2. **User-Only File Fallback**: In headless or minimal container environments lacking a secret service, tokens are stored in a dedicated fallback file (`~/.focuslist/credentials.json`) created with strict user-only read/write file permissions (`0600` on POSIX, explicit user ACL on Windows).
3. **Database Segregation**: OAuth credentials and refresh tokens are **never** stored in the SQLite database (`focuslist.db`). SQLite contains only non-sensitive operational metadata (cache entries, quota ledger, anonymous proposal hashes).
4. **Zero-Token Exposure Rule**: 
   - No token strings, secret keys, or raw bearer headers are ever written to stdout, stderr, debug logs, or tool response payloads (**FR-9.5**, **SEC-SECRETS**).
   - The `auth_status` tool displays: authenticated state, active scopes, token expiration timestamp, and refresh token age in days—**never token values**.

---

## 5. Token Lifecycle, 7-Day Testing Expiry, and Recovery

Because FocusList operates in Google Cloud's **Testing mode** prior to commercial app verification:
- **7-Day Refresh Token Expiry**: In Testing mode, Google refresh tokens issued to unverified test accounts expire after **7 days** (168 hours).
- **Day-5 Proactive Warning (FR-9.5)**: When `auth_status` detects that a refresh token is $\ge 5$ days old, it returns a proactive warning (`AUTH_EXPIRING_SOON`) instructing the learner to re-authenticate before expiration.
- **`invalid_grant` Recovery**: When an access token refresh fails with `invalid_grant` (due to 7-day expiration, user revocation, or password change):
  1. The server immediately halts automatic retries (**COM-6**).
  2. The server returns a structured domain error:
     ```json
     {
       "code": "AUTH_EXPIRED",
       "message": "YouTube authorization has expired or was revoked.",
       "remediation": "Run 'focuslist auth login' to re-authenticate with Google.",
       "retryable": false
     }
     ```
- **Declined Consent**: If the learner cancels or denies Google consent, the server returns `AUTH_CANCELLED` with instructions on required scopes.
- **Channel Eligibility Check**: YouTube requires an active channel to create playlists. FocusList checks channel presence before playlist creation, mapping `youtubeSignupRequired` to `NO_YOUTUBE_CHANNEL` (**FR-9.8**, **NEG-NO-CHANNEL**).

---

## 6. Immediate Revocation and Purge on Logout

Executing `focuslist auth logout` executes a complete cryptographic and data wipe (**FR-9.7**):
1. **Upstream Revocation**: Sends an HTTP POST to `https://oauth2.googleapis.com/revoke?token=<refresh_token>` to invalidate credentials at Google.
2. **Local Credential Destruction**: Deletes all stored tokens from the OS credential store or user-only fallback file.
3. **Authorized Cache Purge**: Immediately executes `DELETE FROM cache_entries WHERE account_id IS NOT NULL;` in SQLite, ensuring no personal user likes, subscriptions, or playlists linger on disk.

---

## 7. Traceability and Verification Plan

- **SRS Requirements**: [FR-9.1–FR-9.9](../../FocusList_SRS_Condensed.docx), [COM-1 to COM-4](../../FocusList_SRS_Condensed.docx), [NFR-SEC](../../FocusList_SRS_Condensed.docx), [TBD-6](../../FocusList_SRS_Condensed.docx), [TBD-7](../../FocusList_SRS_Condensed.docx)
- **Commit Plan**: [Section 3](../../FocusList_Commit_Plan.md#3-provider-cache-quota-and-oauth)
- **Planned Test Cases**:
  - [`SEC-OAUTH`](../../docs/testing/acceptance-cases.md#sec-oauth): Validates PKCE parameters, loopback state check, and least-privilege scoping.
  - [`SEC-SECRETS`](../../docs/testing/acceptance-cases.md#sec-secrets): Asserts absence of tokens and secrets in logs, fixtures, and database.
  - [`NEG-AUTH`](../../docs/testing/acceptance-cases.md#neg-auth): Tests `invalid_grant` recovery, 7-day expiration warnings, and declined consent.
  - [`ST-FR9`](../../docs/testing/acceptance-cases.md#st-fr9): MCP system test for `auth_status` tool and login/logout lifecycle.

---

## 8. Documented Uncertainties and Next Steps

1. **TBD-6 (Minimum Write Scope)**: Need to test whether `youtube.force-ssl` allows full `playlists.insert` and `playlistItems.insert` without triggering authorization errors on brand accounts. Documented for ADR-003 in C10.
2. **TBD-7 (Demo Reauthorization)**: Refresh tokens in testing mode expire in 7 days. A pre-demo checklist must be established before Stage 4 (C31/C36) to ensure the presenter runs `focuslist auth login` on the day of evaluation.
3. **Headless Keyring Fallback**: On Linux without an active X11/Wayland/D-Bus session, `keyring` may raise `NoKeyringError`. The fallback file implementation with `0600` permissions must be tested under Linux CI.
