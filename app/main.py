"""
YouTube Transcript API
Returns transcript with video metadata
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)
import yt_dlp
import re
import os
import shutil
import logging
import requests
from http.cookiejar import MozillaCookieJar
from typing import Optional, Dict, Tuple
from enum import Enum
from pathlib import Path
from app.proxy_manager import proxy_manager

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
MAX_RETRY_ATTEMPTS = 4  # Number of proxy attempts before failing
COOKIE_FILE = os.environ.get('YT_COOKIE_FILE', None)

def get_cookie_file() -> Optional[str]:
    """Find available cookie file"""
    if COOKIE_FILE and Path(COOKIE_FILE).exists():
        logger.info(f"Using cookie file from env: {COOKIE_FILE}")
        return COOKIE_FILE
    
    # Check common locations
    locations = [
        Path('/tmp/cookies.txt'), # Copy to writable location
        Path('/app/cookies.txt'),  # Docker mount point
        Path(__file__).parent.parent / 'cookies.txt',  # Project root
        Path(__file__).parent / 'cookies.txt',  # App directory
        Path.home() / 'Downloads' / 'cookies-youtube-com.txt',  # Downloads
    ]

    # Try to copy read-only cookies to writable location if needed
    ro_cookies = Path('/app/cookies.txt')
    writable_cookies = Path('/tmp/cookies.txt')
    
    if ro_cookies.exists() and not writable_cookies.exists():
        try:
            import shutil
            shutil.copy(ro_cookies, writable_cookies)
            logger.info(f"Copied read-only cookies to writable location: {writable_cookies}")
            return str(writable_cookies)
        except Exception as e:
            logger.warning(f"Failed to copy cookies to writable location: {e}")

    for loc in locations:
        if loc.exists():
            logger.info(f"Found cookie file at: {loc}")
            return str(loc)
    
    logger.warning("No cookie file found - YouTube may require authentication")
    return None


def create_session_with_cookies(cookie_file: Optional[str] = None) -> requests.Session:
    """Create a requests.Session with YouTube cookies loaded from Netscape format file"""
    session = requests.Session()
    
    if cookie_file is None:
        cookie_file = get_cookie_file()
    
    if cookie_file and Path(cookie_file).exists():
        try:
            cookie_jar = MozillaCookieJar(cookie_file)
            cookie_jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies.update(cookie_jar)
            logger.info(f"Loaded {len(cookie_jar)} cookies from {cookie_file}")
        except Exception as e:
            logger.warning(f"Failed to load cookies from {cookie_file}: {e}")
    
    return session


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
        'skip_download': True,
        'ignore_no_formats_error': True,  # We only need metadata, not formats
    }
    
    # Add cookies if available
    cookie_file = get_cookie_file()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file
    
    # Add proxy if available
    proxies = proxy_manager.get_proxy()
    if proxies:
        ydl_opts['proxy'] = proxies['https']
        logger.info(f"Using proxy for metadata: {proxy_manager.get_stats().get('proxy_url', 'configured')}")
    
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


def fetch_transcript_with_retry(video_id: str, language: Optional[str] = None) -> Tuple[list[dict], str]:
    """
    Fetch transcript with automatic proxy rotation and retry logic.
    Uses cookies for authenticated requests when available.
    Returns (raw_transcript_data, language_used).
    Raises appropriate exceptions on failure.
    """
    # Get list of proxies to try (includes None for direct connection)
    proxies_to_try = proxy_manager.get_proxies_for_retry(count=MAX_RETRY_ATTEMPTS - 1)
    
    # Create session with cookies for authenticated requests
    cookie_file = get_cookie_file()
    
    last_error = None
    errors_by_proxy = []
    
    for i, proxies in enumerate(proxies_to_try):
        proxy_url = proxies['https'] if proxies else None
        proxy_desc = proxy_url or "direct connection"
        cookie_desc = "(with cookies)" if cookie_file else "(no cookies)"
        
        try:
            logger.info(f"Attempt {i+1}/{len(proxies_to_try)}: Fetching transcript using {proxy_desc} {cookie_desc}")
            
            # Create fresh session with cookies for each attempt
            http_session = create_session_with_cookies(cookie_file)
            
            # Create API instance with session (for cookies) and optional proxy
            if proxies:
                proxy_config = GenericProxyConfig(
                    http_url=proxies['http'],
                    https_url=proxies['https'],
                )
                ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config, http_client=http_session)
            else:
                ytt_api = YouTubeTranscriptApi(http_client=http_session)
            
            transcript_list = ytt_api.list(video_id)
            
            # Find best transcript
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
                raise NoTranscriptFound(video_id, [], None)
            
            # Fetch and convert
            fetched = transcript.fetch()
            data = fetched.to_raw_data()
            
            logger.info(f"Successfully fetched transcript using {proxy_desc} {cookie_desc}")
            return data, lang_used or 'unknown'
            
        except (TranscriptsDisabled, VideoUnavailable, NoTranscriptFound):
            # These are video-specific errors, not proxy issues - don't retry
            raise
            
        except Exception as e:
            last_error = e
            error_type = type(e).__name__
            errors_by_proxy.append(f"{proxy_desc}: {error_type}")
            logger.warning(f"Attempt {i+1} failed with {proxy_desc}: {error_type} - {str(e)[:100]}")
            
            # Mark proxy as failed (if it was a proxy)
            if proxy_url:
                proxy_manager.mark_proxy_failed(proxy_url)
    
    # All attempts failed
    error_summary = "; ".join(errors_by_proxy)
    logger.error(f"All {len(proxies_to_try)} attempts failed for video {video_id}: {error_summary}")
    raise last_error or Exception(f"Failed to fetch transcript after {len(proxies_to_try)} attempts")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/proxy-stats")
async def proxy_stats():
    """Get current proxy pool statistics"""
    return proxy_manager.get_stats()


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
    
    # Get transcript with automatic retry and proxy rotation
    try:
        data, lang_used = fetch_transcript_with_retry(video_id, language)
        
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
    except NoTranscriptFound:
        raise HTTPException(status_code=404, detail="No transcript found for this video")
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "IP" in error_msg or "block" in error_msg.lower() or "request" in error_msg.lower():
            raise HTTPException(
                status_code=503,
                detail=f"YouTube is blocking requests. All proxy attempts failed: {error_msg}"
            )
        raise HTTPException(status_code=500, detail=error_msg)
