"""
Video to Markdown Processor
Extracts audio from videos using moviepy, transcribes with faster-whisper.
Optimized for low RAM usage (2GB VPS compatible).
"""

import os
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum

from moviepy import VideoFileClip, AudioFileClip

logger = logging.getLogger(__name__)

# Supported video extensions
VIDEO_EXTENSIONS = {
    '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm',
    '.m4v', '.mpeg', '.mpg', '.3gp', '.ogv', '.ts', '.mts'
}

# Supported audio extensions
AUDIO_EXTENSIONS = {
    '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma', '.opus'
}


class WhisperModel(str, Enum):
    """Available model sizes - tiny recommended for 2GB RAM"""
    TINY = "tiny"       # ~1GB RAM, fastest
    BASE = "base"       # ~1.5GB RAM
    SMALL = "small"     # ~2GB RAM (might be tight)


@dataclass
class VideoMetadata:
    """Metadata extracted from a video file"""
    filename: str
    duration: float
    resolution: Optional[Tuple[int, int]] = None
    fps: Optional[float] = None
    file_size: Optional[int] = None


@dataclass
class TranscriptSegment:
    """A segment of transcribed text"""
    start: float
    end: float
    text: str


@dataclass
class ConversionResult:
    """Result of video to markdown conversion"""
    metadata: VideoMetadata
    language: str
    content: str
    segments: List[TranscriptSegment]


def is_video_file(filename: str) -> bool:
    """Check if a filename is a supported video format"""
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def is_audio_file(filename: str) -> bool:
    """Check if a filename is a supported audio format"""
    return Path(filename).suffix.lower() in AUDIO_EXTENSIONS


def is_media_file(filename: str) -> bool:
    """Check if a filename is a supported video or audio format"""
    return is_video_file(filename) or is_audio_file(filename)


def get_video_metadata(video_path: str) -> VideoMetadata:
    """Extract metadata from a video file"""
    path = Path(video_path)
    
    try:
        video = VideoFileClip(video_path)
        metadata = VideoMetadata(
            filename=path.name,
            duration=video.duration,
            resolution=(video.w, video.h) if video.w and video.h else None,
            fps=video.fps,
            file_size=path.stat().st_size if path.exists() else None
        )
        video.close()
        return metadata
    except Exception as e:
        logger.warning(f"Could not extract full metadata: {e}")
        return VideoMetadata(
            filename=path.name,
            duration=0,
            file_size=path.stat().st_size if path.exists() else None
        )


def get_audio_metadata(audio_path: str) -> VideoMetadata:
    """Extract metadata from an audio file"""
    path = Path(audio_path)
    
    try:
        audio = AudioFileClip(audio_path)
        metadata = VideoMetadata(
            filename=path.name,
            duration=audio.duration,
            file_size=path.stat().st_size if path.exists() else None
        )
        audio.close()
        return metadata
    except Exception as e:
        logger.warning(f"Could not extract audio metadata: {e}")
        return VideoMetadata(
            filename=path.name,
            duration=0,
            file_size=path.stat().st_size if path.exists() else None
        )


def extract_audio_from_video(video_path: str, output_format: str = "wav") -> str:
    """
    Extract audio track from a video file.
    Uses WAV for better transcription quality.
    Returns path to extracted audio file (temp file).
    """
    fd, output_path = tempfile.mkstemp(suffix=f".{output_format}")
    os.close(fd)
    
    logger.info(f"Extracting audio from: {video_path}")
    
    try:
        video = VideoFileClip(video_path)
        
        if video.audio is None:
            video.close()
            raise ValueError("Video file has no audio track")
        
        # 16kHz mono is optimal for whisper
        video.audio.write_audiofile(
            output_path,
            fps=16000,
            nbytes=2,
            codec='pcm_s16le' if output_format == 'wav' else None,
            logger=None
        )
        video.close()
        
        logger.info(f"Audio extracted to: {output_path}")
        return output_path
        
    except Exception as e:
        if os.path.exists(output_path):
            os.unlink(output_path)
        raise RuntimeError(f"Failed to extract audio: {e}") from e


# Global model instance (lazy loaded to save memory)
_whisper_model = None
_whisper_model_name = None


def get_whisper_model(model_name: str = "tiny"):
    """Get or load whisper model (lazy loading to save RAM)"""
    global _whisper_model, _whisper_model_name
    
    if _whisper_model is None or _whisper_model_name != model_name:
        from faster_whisper import WhisperModel
        
        logger.info(f"Loading faster-whisper model: {model_name}")
        
        # Use int8 quantization for lower memory usage
        _whisper_model = WhisperModel(
            model_name,
            device="cpu",
            compute_type="int8",  # Lower memory usage
            cpu_threads=2,  # Limit threads for VPS
        )
        _whisper_model_name = model_name
        logger.info(f"Model loaded: {model_name}")
    
    return _whisper_model


def transcribe_audio(audio_path: str, model_name: str = "tiny", language: Optional[str] = None) -> Tuple[str, List[TranscriptSegment]]:
    """
    Transcribe audio file using faster-whisper.
    Returns (detected_language, segments)
    """
    model = get_whisper_model(model_name)
    
    logger.info(f"Transcribing: {audio_path}")
    
    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=1,  # Lower memory
        best_of=1,    # Lower memory
        vad_filter=True,  # Skip silence
    )
    
    segments = []
    for seg in segments_iter:
        segments.append(TranscriptSegment(
            start=seg.start,
            end=seg.end,
            text=seg.text.strip()
        ))
    
    detected_lang = info.language if info.language else "unknown"
    logger.info(f"Transcription complete: {len(segments)} segments, language: {detected_lang}")
    
    return detected_lang, segments


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def segments_to_markdown(segments: List[TranscriptSegment], metadata: VideoMetadata, language: str) -> str:
    """Convert transcript segments to formatted markdown"""
    lines = []
    
    # Title from filename
    title = Path(metadata.filename).stem.replace("_", " ").replace("-", " ")
    lines.append(f"# {title}")
    lines.append("")
    
    # Metadata
    lines.append("## Info")
    lines.append("")
    lines.append(f"- **File:** `{metadata.filename}`")
    
    duration_h = int(metadata.duration // 3600)
    duration_m = int((metadata.duration % 3600) // 60)
    duration_s = int(metadata.duration % 60)
    if duration_h > 0:
        lines.append(f"- **Duration:** {duration_h}h {duration_m}m {duration_s}s")
    else:
        lines.append(f"- **Duration:** {duration_m}m {duration_s}s")
    
    lines.append(f"- **Language:** {language}")
    
    if metadata.resolution:
        lines.append(f"- **Resolution:** {metadata.resolution[0]}x{metadata.resolution[1]}")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Transcript")
    lines.append("")
    
    # Group into paragraphs (~30s chunks)
    current_para = []
    para_start = 0
    
    for seg in segments:
        if not current_para:
            para_start = seg.start
        
        current_para.append(seg.text)
        
        # Break on sentence end or after 30s
        if (seg.end - para_start > 30) or seg.text.endswith(('.', '?', '!')):
            if current_para:
                ts = format_timestamp(para_start)
                text = " ".join(current_para)
                lines.append(f"**[{ts}]** {text}")
                lines.append("")
                current_para = []
    
    # Remaining text
    if current_para:
        ts = format_timestamp(para_start)
        text = " ".join(current_para)
        lines.append(f"**[{ts}]** {text}")
        lines.append("")
    
    return "\n".join(lines)


def convert_video_to_markdown(
    media_path: str,
    model: str = "tiny",
    language: Optional[str] = None
) -> ConversionResult:
    """
    Convert a video or audio file to markdown transcript.
    
    Args:
        media_path: Path to video/audio file
        model: Whisper model (tiny recommended for 2GB RAM)
        language: Source language or None for auto-detect
    """
    path = Path(media_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {media_path}")
    
    is_video = is_video_file(path.name)
    is_audio = is_audio_file(path.name)
    
    if not is_video and not is_audio:
        raise ValueError(f"Unsupported format: {path.suffix}")
    
    # Get metadata
    if is_video:
        metadata = get_video_metadata(media_path)
    else:
        metadata = get_audio_metadata(media_path)
    
    # Extract audio if video
    audio_path = media_path
    temp_audio = None
    
    try:
        if is_video:
            temp_audio = extract_audio_from_video(media_path)
            audio_path = temp_audio
        
        # Transcribe
        detected_lang, segments = transcribe_audio(audio_path, model, language)
        
        # Generate markdown
        markdown = segments_to_markdown(segments, metadata, detected_lang)
        
        return ConversionResult(
            metadata=metadata,
            language=detected_lang,
            content=markdown,
            segments=segments
        )
        
    finally:
        if temp_audio and os.path.exists(temp_audio):
            os.unlink(temp_audio)
