# Media Service — API Documentation

**Base path:** `/api/v1/media`

> All endpoints require `Authorization: Bearer <token>`

The Media Service handles file uploads (images & videos) with automatic:
- **Compression** (images resized, videos re-encoded)
- **NSFW/AI moderation** (NudeNet detection)
- **CDN storage** via Cloudinary (round-robin across configured cloud accounts)

---

## Endpoints

### POST /api/v1/media/upload
Upload an image or video file. The file is automatically compressed and scanned for NSFW content before being stored in Cloudinary.

**Accepted formats:**
- Images: `jpeg`, `png`, `webp`, `gif`
- Videos: `mp4`, `webm`, `mov`, `avi`

**Form Fields:**
- `file` — The file to upload (multipart/form-data)
- `purpose` — (query param) Why this file is being uploaded: `"avatar"`, `"post"`, `"community"` (default: `"post"`)

**cURL:**
```bash
# Upload an image for a post
curl -X POST "{{BASE_URL}}/api/v1/media/upload?purpose=post" \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/your/image.jpg"

# Upload an avatar image
curl -X POST "{{BASE_URL}}/api/v1/media/upload?purpose=avatar" \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/avatar.png"

# Upload a video
curl -X POST "{{BASE_URL}}/api/v1/media/upload?purpose=post" \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/video.mp4"
```

**Response 200 OK (Normal file, not flagged):**
```json
{
  "url": "http://res.cloudinary.com/duijznyhu/image/upload/v.../astu/post/user-uuid/abc123.jpg",
  "secure_url": "https://res.cloudinary.com/duijznyhu/image/upload/v.../astu/post/user-uuid/abc123.jpg",
  "public_id": "astu/post/user-uuid/abc123",
  "object_name": "astu/post/user-uuid/abc123",
  "is_flagged": false,
  "moderation_labels": []
}
```

**Response 200 OK (NSFW content detected):**
```json
{
  "url": "https://res.cloudinary.com/...",
  "secure_url": "https://res.cloudinary.com/...",
  "public_id": "astu/post/user-uuid/abc123",
  "object_name": "astu/post/user-uuid/abc123",
  "is_flagged": true,
  "moderation_labels": ["FEMALE_BREAST_EXPOSED", "BUTTOCKS_EXPOSED"]
}
```
> The file is still uploaded but the `is_flagged: true` flag means your app should warn the user or reject the post.

**Response 400 Bad Request (wrong file type):**
```json
{"detail": "Only images (jpeg, png, webp, gif) and videos (mp4, webm, mov, avi) are allowed."}
```

**Response 400 Bad Request (empty file):**
```json
{"detail": "Empty file"}
```

**Response 503 Service Unavailable (Cloudinary not configured):**
```json
{"detail": "Cloudinary not configured. Set CLOUDINARY_CLOUDS_JSON with at least one cloud."}
```

---

### POST /api/v1/media/upload-url
⚠️ **Legacy MinIO endpoint.** Use `/upload` instead for production Cloudinary uploads.

Generates a pre-signed URL for directly uploading a file to MinIO S3-compatible storage.

**Request body:**
```json
{
  "filename": "profile_photo.jpg",
  "content_type": "image/jpeg",
  "purpose": "avatar"
}
```

**cURL:**
```bash
curl -X POST {{BASE_URL}}/api/v1/media/upload-url \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"filename": "profile_photo.jpg", "content_type": "image/jpeg", "purpose": "avatar"}'
```

**Response 200 OK:**
```json
{
  "upload_url": "http://minio:9000/astu-media/avatar/user-uuid/550e8400-e29b-11d4-a716.jpg?X-Amz-Signature=...",
  "object_name": "avatar/user-uuid/550e8400-e29b-11d4-a716.jpg",
  "download_url": "http://minio:9000/astu-media/avatar/user-uuid/550e8400-e29b-11d4-a716.jpg?X-Amz-Signature=..."
}
```

---

### POST /api/v1/media/download-url
Get a download URL for a stored object. Accepts both Cloudinary URLs (returned as-is) and MinIO object names (returns a presigned URL).

**Request body:**
```json
{
  "object_name": "avatar/user-uuid/550e8400.jpg"
}
```

**cURL:**
```bash
# MinIO object name
curl -X POST {{BASE_URL}}/api/v1/media/download-url \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"object_name": "avatar/user-uuid/550e8400.jpg"}'

# Full Cloudinary URL (returned unchanged)
curl -X POST {{BASE_URL}}/api/v1/media/download-url \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"object_name": "https://res.cloudinary.com/.../image.jpg"}'
```

**Response 200 OK:**
```json
{
  "download_url": "https://res.cloudinary.com/.../image.jpg"
}
```

---

### DELETE /api/v1/media/{object_name}
Delete a media file. Users can only delete their own files.

> For Cloudinary URLs, the URL path must contain `/user-uuid/`.
> For MinIO objects, the path must start with `avatar/user-uuid/` or `post/user-uuid/`.

**cURL:**
```bash
# Delete a Cloudinary file (URL-encode the path)
curl -X DELETE "{{BASE_URL}}/api/v1/media/https%3A%2F%2Fres.cloudinary.com%2F.../image.jpg" \
  -H "Authorization: Bearer <token>"

# Delete a MinIO object
curl -X DELETE "{{BASE_URL}}/api/v1/media/avatar/user-uuid/550e8400.jpg" \
  -H "Authorization: Bearer <token>"
```

**Response 200 OK:**
```json
{"status": "deleted"}
```

**Response 403 Forbidden:**
```json
{"detail": "Not authorized to delete this file"}
```

**Response 404 Not Found:**
```json
{"detail": "Object not found"}
```
