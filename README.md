# YouTube Transcript API

Dockerized API to get YouTube video transcripts with metadata.

## Deploy

```bash
docker compose up -d --build
```

## Usage

```
GET /transcript/{video_id}?language=en&format=text
```

**Parameters:**
- `video_id` - YouTube video ID or URL
- `language` - Language code (optional, defaults to English)
- `format` - `text`, `json`, `srt`, `vtt` (default: text)

## Example

```bash
curl "http://localhost:8000/transcript/dQw4w9WgXcQ?format=text"
```

**Response:**
```json
{
  "metadata": {
    "video_id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "author": "Rick Astley",
    "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
    "upload_date": "20091025",
    "duration": 212,
    "view_count": 1500000000,
    "like_count": 16000000,
    "description": "...",
    "thumbnail": "https://...",
    "tags": ["rick astley", "never gonna give you up", "..."]
  },
  "language": "en",
  "transcript": "We're no strangers to love...",
  "format": "text"
}
```

## n8n HTTP Request Node

- **URL**: `http://yt-transcript-api:8000/transcript/{{ $json.video_id }}`
- **Method**: GET

Or if running on same host:
- **URL**: `http://host.docker.internal:8000/transcript/{{ $json.video_id }}`
