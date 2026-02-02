# YouTube Transcript & Video-to-Markdown API

Dockerized API for:
- YouTube video transcripts with metadata
- **Video/Audio to Markdown conversion** using OpenAI Whisper
- File/URL to Markdown using Microsoft MarkItDown

## Deploy

```bash
docker compose up -d --build
```

> **Note:** First run will download the Whisper model (~150MB for base). Larger models provide better accuracy but require more resources.

## Video to Markdown

Convert video files (MKV, MP4, AVI, etc.) or audio files to formatted Markdown transcripts using OpenAI Whisper speech recognition.

### Supported Formats

**Video:** `.mkv`, `.mp4`, `.avi`, `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.mpeg`, `.mpg`, `.3gp`, `.ogv`, `.ts`, `.mts`

**Audio:** `.mp3`, `.wav`, `.flac`, `.aac`, `.ogg`, `.m4a`, `.wma`, `.opus`

### API Usage

```bash
# Basic conversion (uses base model)
curl -X POST "http://localhost:8000/convert/video-to-markdown" \
     -F "file=@/path/to/video.mkv"

# With options
curl -X POST "http://localhost:8000/convert/video-to-markdown?model=small&language=en&include_timestamps=true" \
     -F "file=@/path/to/video.mkv"
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `file` | required | Video or audio file to transcribe |
| `model` | `base` | Whisper model: `tiny`, `base`, `small`, `medium`, `large`, `turbo` |
| `language` | auto | Source language code (e.g., `en`, `es`, `fr`) |
| `include_timestamps` | `true` | Include timestamps in markdown output |
| `include_segments` | `false` | Include detailed segment timing in response |

### Model Selection Guide

| Model | Speed | Accuracy | VRAM | Best For |
|-------|-------|----------|------|----------|
| `tiny` | ~10x realtime | Good | ~1GB | Quick drafts, short videos |
| `base` | ~7x realtime | Better | ~1GB | **Recommended default** |
| `small` | ~4x realtime | Great | ~2GB | Quality transcriptions |
| `medium` | ~2x realtime | Excellent | ~5GB | Professional use |
| `large` | ~1x realtime | Best | ~10GB | Maximum accuracy |
| `turbo` | ~1x realtime | Excellent | ~6GB | Optimized large model |

### Response Example

```json
{
  "metadata": {
    "filename": "lecture.mkv",
    "duration": 3600,
    "duration_human": "1h 0m 0s",
    "resolution": "1920x1080",
    "fps": 30.0,
    "file_size_mb": 1250.5
  },
  "language": "en",
  "text": "Welcome to today's lecture on machine learning...",
  "markdown": "# lecture\n\n## Metadata\n\n- **Source File:** `lecture.mkv`\n- **Duration:** 1h 0m 0s\n...",
  "segments": null
}
```

### n8n Workflow

Import `workflow.json` to n8n for automated Google Drive video conversion:

1. **Watch folder** → Monitors Google Drive folder for new videos
2. **Filter** → Only processes video files (video/* mime type)
3. **Download** → Downloads video from Google Drive
4. **Convert** → Sends to API for transcription
5. **Upload** → Saves markdown to same folder

**Setup:**
1. Import `workflow.json` into n8n
2. Update `YOUR_FOLDER_ID_HERE` with your Google Drive folder ID
3. Connect your Google Drive OAuth credentials
4. Activate the workflow

---

## YouTube Transcript

```
GET /transcript/{video_id}?language=en&format=text
```

**Parameters:**
- `video_id` - YouTube video ID or URL
- `language` - Language code (optional, defaults to English)
- `format` - `text`, `json`, `srt`, `vtt` (default: text)

### Example

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

---

## File/URL to Markdown

Convert files or URLs to Markdown using [Microsoft MarkItDown](https://github.com/microsoft/markitdown).

### Usage

**Convert URL:**
```bash
curl -X POST "http://localhost:8000/convert/markdown" \
     -F "url=https://en.wikipedia.org/wiki/Microsoft"
```

**Convert File:**
```bash
curl -X POST "http://localhost:8000/convert/markdown" \
     -F "file=@/path/to/document.pdf"
```

---

## n8n HTTP Request Node

- **URL**: `http://yt-transcript-api:8000/convert/video-to-markdown`
- **Method**: POST
- **Body Type**: Multipart Form Data

Or if running on same host:
- **URL**: `http://host.docker.internal:8000/convert/video-to-markdown`

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/proxy-stats` | GET | Proxy pool statistics |
| `/transcript/{video_id}` | GET | Get YouTube transcript |
| `/convert/markdown` | POST | Convert file/URL to markdown |
| `/convert/video-to-markdown` | POST | Convert video/audio to markdown |
| `/convert/video/formats` | GET | List supported formats |
