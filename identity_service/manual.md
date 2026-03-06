# Identity Service — Manual configuration

This document lists everything you must configure manually for:

- **Email verification** (link sent on register; only `@astu.edu.et` / `.edu.et` allowed)
- **Forgot password** (OTP sent to user email)

---

## 1. Environment variables (.env)

### 1.1 Database
| Variable | Description | Example |
|----------|-------------|---------|
| `IDENTITY_DATABASE_URL` | PostgreSQL connection string | `postgresql://identity_user:identity_pass@localhost:5432/identity_db` |

### 1.2 JWT
| Variable | Description | Example |
|----------|-------------|---------|
| `JWT_SECRET_KEY` | Secret for signing tokens | long random string |
| `JWT_ALGORITHM` | Algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL | `15` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `30` |

### 1.3 Email (SMTP) — required for verification and forgot-password
| Variable | Description | Example |
|----------|-------------|---------|
| `SMTP_HOST` | Mail server hostname | `smtp.gmail.com` |
| `SMTP_PORT` | Port (587 TLS, 465 SSL) | `587` |
| `SMTP_USER` | Username / API user | your email or API user |
| `SMTP_PASSWORD` | Password or API key | app password or API key |
| `SMTP_FROM_EMAIL` | Sender address | `noreply@astu.edu.et` |
| `SMTP_FROM_NAME` | Sender name | `ASTU Connect` |
| `SMTP_USE_TLS` | Use STARTTLS | `true` |

### 1.4 App URLs (for verification link)
| Variable | Description | Example |
|----------|-------------|---------|
| `APP_BASE_URL` | Base URL of frontend (no trailing slash) | `https://astuconnect.example.com` |
| `VERIFY_EMAIL_PATH` | Path for verification link | `/verify-email` |
| Verification link format | | `{APP_BASE_URL}{VERIFY_EMAIL_PATH}?token=<token>` |

### 1.5 Email verification
| Variable | Description | Example |
|----------|-------------|---------|
| `VERIFICATION_TOKEN_EXPIRE_HOURS` | How long the verification link is valid | `24` |

### 1.6 Forgot password (OTP)
| Variable | Description | Example |
|----------|-------------|---------|
| `OTP_LENGTH` | Number of digits in OTP | `6` |
| `OTP_EXPIRE_MINUTES` | OTP validity | `15` |

### 1.7 Feature flag
| Variable | Description | Example |
|----------|-------------|---------|
| `REQUIRE_EMAIL_VERIFICATION` | Require email_verified to login | `true` |

### 1.8 Kafka
| Variable | Description |
|----------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka brokers, e.g. `localhost:9092` |

---

## 2. Email provider setup

### Option A: Gmail (development)
1. Use a Google account; enable 2FA.
2. Create an **App Password** for "Mail".
3. Set: `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`, `SMTP_USER=your@gmail.com`, `SMTP_PASSWORD=<app password>`.

### Option B: SendGrid
1. Create account, get API key.
2. Set: `SMTP_HOST=smtp.sendgrid.net`, `SMTP_PORT=587`, `SMTP_USER=apikey`, `SMTP_PASSWORD=<API key>`, `SMTP_FROM_EMAIL` = verified sender in SendGrid.

### Option C: SMTP server (@astu.edu.et)
1. Get host, port, username, password from IT.
2. Set all `SMTP_*` variables accordingly.

---

## 3. Behaviour summary

- **Registration**: Only emails ending with `@astu.edu.et` or `.edu.et` are allowed. User is created with `email_verified=False`, `is_astu_student=True`. A verification link is sent to the email.
- **Email verification**: User opens link → token validated → `email_verified=True`.
- **Login**: If `REQUIRE_EMAIL_VERIFICATION=true`, login is allowed only when `email_verified=True`.
- **Forgot password**: User requests reset → OTP sent to email → user submits OTP + new password → password reset.

---

## 4. Pre-launch checklist

- [ ] All `SMTP_*` and `APP_BASE_URL` / `VERIFY_EMAIL_PATH` set in `.env`.
- [ ] `APP_BASE_URL` points to the real frontend URL.
- [ ] Database running; service started at least once so tables are created.
- [ ] Frontend: page for `verify-email?token=...` that calls the verify endpoint (or user opens link to API directly).
- [ ] Frontend: "Forgot password" flow (request OTP → enter OTP + new password → call reset endpoint).
- [ ] Existing users: If you have existing accounts, consider a one-time update to set `email_verified=True` so they are not locked out (e.g. `UPDATE users SET email_verified = true WHERE ...`).
