"""
YouTube Transcript API
Returns transcript with video metadata
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
import yt_dlp
import re
import os
from typing import Optional
from enum import Enum
from pathlib import Path

# Cookie file path - configurable via environment variable
# Default: ./cookies.txt (relative to app) or ~/Downloads/cookies-youtube-com.txt
COOKIE_FILE = os.environ.get('YT_COOKIE_FILE', None)

def get_cookie_file() -> Optional[str]:
    """Find available cookie file"""
    if COOKIE_FILE and Path(COOKIE_FILE).exists():
        return COOKIE_FILE
    
    # Check common locations
    locations = [
        Path(__file__).parent.parent / 'cookies.txt',  # Project root
        Path(__file__).parent / 'cookies.txt',  # App directory
        Path.home() / 'Downloads' / 'cookies-youtube-com.txt',  # Downloads
        Path('/app/cookies.txt'),  # Docker/VPS common location
    ]
    
    for loc in locations:
        if loc.exists():
            return str(loc)
    return None


app = FastAPI(
    title="YouTube Transcript API",
    description="Get YouTube video transcripts with metadata",
    version="1.0.0",
)


class OutputFormat(str, Enum):
    text = "text"
    json = "json"
    srt = "srt"
    vtt = "vtt"


class VideoMetadata(BaseModel):
    video_id: str
    title: str
    author: str
    channel_id: Optional[str] = None
    upload_date: Optional[str] = None
    duration: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    description: Optional[str] = None
    thumbnail: Optional[str] = None
    tags: Optional[list[str]] = None


class TranscriptSegment(BaseModel):
    text: str
    start: float
    duration: float


class TranscriptResponse(BaseModel):
    metadata: VideoMetadata
    language: str
    transcript: str | list[TranscriptSegment]
    format: OutputFormat


def extract_video_id(url_or_id: str) -> str:
    """Extract video ID from YouTube URL or return ID directly"""
    patterns = [
        r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/)([a-zA-Z0-9_-]{11})',
        r'^([a-zA-Z0-9_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    raise ValueError(f"Invalid YouTube URL or video ID: {url_or_id}")


def get_video_metadata(video_id: str) -> VideoMetadata:
    """Fetch video metadata using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
    }
    
    # Add cookies if available
    cookie_file = get_cookie_file()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            
            return VideoMetadata(
                video_id=video_id,
                title=info.get('title', ''),
                author=info.get('uploader', ''),
                channel_id=info.get('channel_id'),
                upload_date=info.get('upload_date'),
                duration=info.get('duration'),
                view_count=info.get('view_count'),
                like_count=info.get('like_count'),
                description=info.get('description'),
                thumbnail=info.get('thumbnail'),
                tags=info.get('tags'),
            )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Could not fetch video metadata: {str(e)}")


def format_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """Convert seconds to VTT timestamp"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def transcript_to_srt(transcript: list[dict]) -> str:
    srt = []
    for i, seg in enumerate(transcript, 1):
        start = seg['start']
        end = start + seg['duration']
        srt.append(f"{i}")
        srt.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
        srt.append(seg['text'])
        srt.append("")
    return "\n".join(srt)


def transcript_to_vtt(transcript: list[dict]) -> str:
    vtt = ["WEBVTT", ""]
    for seg in transcript:
        start = seg['start']
        end = start + seg['duration']
        vtt.append(f"{format_timestamp_vtt(start)} --> {format_timestamp_vtt(end)}")
        vtt.append(seg['text'])
        vtt.append("")
    return "\n".join(vtt)


def transcript_to_text(transcript: list[dict]) -> str:
    return " ".join(seg['text'] for seg in transcript)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/transcript/{video_id}", response_model=TranscriptResponse)
async def get_transcript(
    video_id: str,
    language: Optional[str] = None,
    format: OutputFormat = OutputFormat.text
):
    """
    Get transcript and metadata for a YouTube video.
    
    - **video_id**: YouTube video ID or full URL
    - **language**: Preferred language code (optional)
    - **format**: text, json, srt, or vtt
    """
    try:
        video_id = extract_video_id(video_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Get metadata
    metadata = get_video_metadata(video_id)
    
    # Get transcript
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)
        
        transcript = None
        lang_used = None
        
        if language:
            try:
                transcript = transcript_list.find_transcript([language])
                lang_used = language
            except NoTranscriptFound:
                for t in transcript_list:
                    if t.is_translatable:
                        transcript = t.translate(language)
                        lang_used = language
                        break
        
        if transcript is None:
            try:
                transcript = transcript_list.find_transcript(['en'])
                lang_used = 'en'
            except NoTranscriptFound:
                for t in transcript_list:
                    transcript = t
                    lang_used = t.language_code
                    break
        
        if transcript is None:
            raise HTTPException(status_code=404, detail="No transcript found")
        
        fetched = transcript.fetch()
        # Convert to raw data format for compatibility with formatting functions
        data = fetched.to_raw_data()
        
        if format == OutputFormat.json:
            formatted = [TranscriptSegment(text=s['text'], start=s['start'], duration=s['duration']) for s in data]
        elif format == OutputFormat.srt:
            formatted = transcript_to_srt(data)
        elif format == OutputFormat.vtt:
            formatted = transcript_to_vtt(data)
        else:
            formatted = transcript_to_text(data)
        
        return TranscriptResponse(
            metadata=metadata,
            language=lang_used,
            transcript=formatted,
            format=format
        )
        
    except TranscriptsDisabled:
        raise HTTPException(status_code=403, detail="Transcripts disabled for this video")
    except VideoUnavailable:
        raise HTTPException(status_code=404, detail="Video unavailable")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
