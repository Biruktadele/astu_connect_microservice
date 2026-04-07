# Identity Service — API Documentation

**Base path:** `/api/v1/auth`, `/api/v1/users`

> Replace `{{BASE_URL}}` with your actual host (see [documentation/README.md](./README.md)).

---

## Authentication Endpoints

### POST /api/v1/auth/register
Register a new ASTU student account. Email must end in `@astu.edu.et` or `.edu.et`.

**Request body:**
```json
{
  "email": "student@astu.edu.et",
  "username": "biruk_tadele",
  "password": "SecurePassword123!",
  "display_name": "Biruk Tadele",
  "department": "Computer Science",
  "year_of_study": 3
}
```

**cURL:**
```bash
curl -X POST  http://13.63.134.156/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "dagibura33@gmail.com",
    "username": "biruk_tadele",
    "password": "12345678",
    "display_name": "Biruk Tadele",
    "department": "Computer Science",
    "year_of_study": 3
  }'
```

**Response 201 Created:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "email": "student@astu.edu.et",
  "username": "biruk_tadele",
  "display_name": "Biruk Tadele",
  "department": "Computer Science",
  "year_of_study": 3,
  "bio": "",
  "avatar_url": "",
  "is_active": true,
  "email_verified": false,
  "is_astu_student": true,
  "roles": ["student"],
  "followers_count": 0,
  "following_count": 0
}
```

**Response 400 Bad Request:**
```json
{"detail": "Email already registered"}
```

---

### GET /api/v1/auth/verify-email
Verify email address using the token sent to the user's email.

**Query params:** `token=<verification_token>`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/auth/verify-email?token=abc123xyz"
```

**Response 200 OK:**
```json
{"message": "Email verified successfully"}
```

**Response 400 Bad Request:**
```json
{"detail": "Invalid or expired token"}
```

---

### POST /api/v1/auth/resend-verification
Re-send the email verification link. Safe against email enumeration — always returns `200` for unknown emails.

**Request body:**
```json
{"email": "student@astu.edu.et"}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/auth/resend-verification \
  -H "Content-Type: application/json" \
  -d '{"email": "student@astu.edu.et"}'
```

**Response 200 OK (email sent or address not found — same response to avoid enumeration):**
```json
{"message": "If that email is registered and unverified, a new link has been sent"}
```

**Response 400 Bad Request (already verified):**
```json
{"detail": "Email is already verified"}
```

---

### POST /api/v1/auth/login
Login and receive access + refresh tokens.

**Request body:**
```json
{
  "email": "student@astu.edu.et",
  "password": "SecurePassword123!"
}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "student@astu.edu.et", "password": "SecurePassword123!"}'
```

**Response 200 OK:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
  "token_type": "bearer"
}
```

**Response 401 Unauthorized:**
```json
{"detail": "Invalid credentials"}
```

**Response 403 Forbidden:**
```json
{"detail": "Verify your email before logging in"}
```

---

### POST /api/v1/auth/refresh
Get a new access token using your refresh token.

**Request body:**
```json
{
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4..."
}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4..."}'
```

**Response 200 OK:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "dGhpcyBpcyBhIHJlZnJlc2ggdG9rZW4...",
  "token_type": "bearer"
}
```

---

### POST /api/v1/auth/forgot-password
Request a password reset OTP sent to the email.

**Request body:**
```json
{"email": "student@astu.edu.et"}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email": "student@astu.edu.et"}'
```

**Response 200 OK:**
```json
{"message": "If an account with that email exists, a reset code has been sent"}
```

---

### POST /api/v1/auth/reset-password
Reset password using the OTP code received by email.

**Request body:**
```json
{
  "email": "student@astu.edu.et",
  "otp": "123456",
  "new_password": "NewSecurePassword123!"
}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{"email": "student@astu.edu.et", "otp": "123456", "new_password": "NewSecurePassword123!"}'
```

**Response 200 OK:**
```json
{"message": "Password reset successfully"}
```

**Response 400 Bad Request:**
```json
{"detail": "Invalid or expired OTP"}
```

---

## User Profile Endpoints

> All endpoints below require `Authorization: Bearer <token>`

### GET /api/v1/users/me
Get the currently authenticated user's profile.

**cURL:**
```bash
curl {{BASE_URL}}/api/v1/users/me \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "email": "student@astu.edu.et",
  "username": "biruk_tadele",
  "display_name": "Biruk Tadele",
  "department": "Computer Science",
  "year_of_study": 3,
  "bio": "I love coding",
  "avatar_url": "https://res.cloudinary.com/.../avatar.jpg",
  "is_active": true,
  "email_verified": true,
  "is_astu_student": true,
  "roles": ["student"],
  "followers_count": 42,
  "following_count": 17
}
```

---

### PATCH /api/v1/users/me
Update the current user's profile fields (partial update — only include fields to change).

**Request body (all optional):**
```json
{
  "display_name": "Biruk T.",
  "bio": "Final year CS student",
  "avatar_url": "https://res.cloudinary.com/.../new_avatar.jpg",
  "department": "Software Engineering",
  "year_of_study": 4
}
```

**cURL:**
```bash
curl -X PATCH {{BASE_URL}}/api/v1/users/me \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"bio": "Final year CS student"}'
```

**Response 200 OK:** Same as `GET /users/me`

---

### GET /api/v1/users/{user_id}
Get any user's public profile.

**cURL:**
```bash
curl {{BASE_URL}}/api/v1/users/3fa85f64-5717-4562-b3fc-2c963f66afa6 \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:** Same schema as `GET /users/me`

**Response 404 Not Found:**
```json
{"detail": "User not found"}
```

---

### GET /api/v1/users/{user_id}/followers
List all followers of a user.

**Query params:** `limit=50`, `offset=0`

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/users/3fa85f64.../followers?limit=20&offset=0" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{
  "users": [
    {
      "id": "...",
      "username": "john_doe",
      "display_name": "John Doe",
      "avatar_url": "...",
      "followers_count": 10,
      "following_count": 5
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

---

### GET /api/v1/users/{user_id}/following
List all users that a user is following.

**cURL:**
```bash
curl "{{BASE_URL}}/api/v1/users/3fa85f64.../following?limit=20" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:** Same schema as `/followers`

---

## Follow / Block Endpoints

### POST /api/v1/users/{user_id}/follow
Follow a user.

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/users/3fa85f64.../follow \
  -H "Authorization: Bearer <token>"
```

**Response 201 Created:**
```json
{"status": "followed"}
```

**Response 400 Bad Request:**
```json
{"detail": "Already following this user"}
```

---

### DELETE /api/v1/users/{user_id}/follow
Unfollow a user.

**cURL:**
```bash
curl -X DELETE {{BASE_URL}}/api/v1/users/3fa85f64.../follow \
  -H "Authorization: Bearer <token>"
```

**Response 204 No Content**

---

### POST /api/v1/users/{user_id}/block
Block a user (also removes follow relationship).

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/users/3fa85f64.../block \
  -H "Authorization: Bearer <token>"
```

**Response 201 Created:**
```json
{"status": "blocked"}
```

---

### DELETE /api/v1/users/{user_id}/block
Unblock a user.

**cURL:**
```bash
curl -X DELETE {{BASE_URL}}/api/v1/users/3fa85f64.../block \
  -H "Authorization: Bearer <token>"
```

**Response 204 No Content**
