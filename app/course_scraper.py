"""
Course Video Scraper
Scrapes video URLs from acquisition.com courses for n8n to download and organize.
"""

import re
import json
import logging
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.acquisition.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Course definitions
COURSES = {
    "scaling": {
        "name": "1-scaling-course",
        "pages": [
            "/training/scalingstart", "/training/context", "/training/improvise",
            "/training/monetize", "/training/advertise", "/training/stabilize",
            "/training/prioritize", "/training/productize", "/training/optimize",
            "/training/categorize", "/training/specialize", "/training/capitalize",
            "/training/free-bonus",
        ]
    },
    "offers": {
        "name": "2-offers-course",
        "pages": [
            "/training/offers", "/training/offers2", "/training/offers3",
            "/training/offers4", "/training/offers5", "/training/offers6",
            "/training/offers7", "/training/offers8", "/training/offers9",
            "/training/offers10", "/training/offersfreebonus",
        ]
    },
    "leads": {
        "name": "3-leads-course",
        "pages": ["/training/leads"] + [f"/training/leads{i}" for i in range(1, 18)] + ["/training/leadsfreebonus"]
    },
    "money": {
        "name": "4-money-models-course",
        "pages": [
            # Core concepts (7 videos)
            "/training/money/context",
            "/training/money/how-businesses-make-money",
            "/training/money/cac",
            "/training/money/gross-profit",
            "/training/money/payback-period",
            "/training/money/cfa",
            "/training/money/money-models-offer-stacks",
            # Offer types (4 videos)
            "/training/money/offer-types",
            "/training/money/ride-along-apprenticeship",
            "/training/money/attraction-offers",
            "/training/money/win-your-money-back",
            "/training/money/free-giveaways",
            "/training/money/decoy-offers",
            # Free offers (4 videos)
            "/training/money/free-trials",
            "/training/money/free-with-consumption",
            # Payment strategies (4 videos)
            "/training/money/pay-less-now",
            "/training/money/payment-plans",
            "/training/money/waived-fee",
            "/training/money/buy-x-get-y",
            # Upsells (6 videos)
            "/training/money/upsell-offers",
            "/training/money/classic-upsell",
            "/training/money/anchor-upsell",
            "/training/money/menu-upsell",
            "/training/money/rollover-upsell",
            "/training/money/downsells",
            "/training/money/feature-downsells",
            # Continuity (3 videos)
            "/training/money/continuity-offers",
            "/training/money/continuity-bonus",
            "/training/money/continuity-discounts",
            # Wrap-up (3 videos)
            "/training/money/make-your-money-model",
            "/training/money/ten-years-ten-minutes",
            "/training/money/audiobook",
            "/training/money/final-words",
        ],
        "auto_discover": True
    },
}


# Pydantic models for API responses
class VideoInfo(BaseModel):
    """Information about a single video."""
    url: str = Field(..., description="Direct video URL or embed URL")
    type: str = Field(..., description="Video type: 'direct' (mp4) or 'embed' (iframe)")
    source: str = Field(..., description="Video source: hubspot, wistia, vimeo, youtube, etc.")


class PageVideos(BaseModel):
    """Videos found on a single page."""
    page_url: str = Field(..., description="Original page URL")
    slug: str = Field(..., description="Page slug for filename")
    index: int = Field(..., description="Page index within course")
    videos: List[VideoInfo] = Field(default_factory=list, description="Videos found on page")
    suggested_filename: str = Field(..., description="Suggested filename for the video")


class CourseVideos(BaseModel):
    """All videos for a course."""
    course_key: str = Field(..., description="Course identifier key")
    course_name: str = Field(..., description="Course folder name")
    total_pages: int = Field(..., description="Total pages in course")
    total_videos: int = Field(..., description="Total videos found")
    pages: List[PageVideos] = Field(default_factory=list, description="Pages with videos")


class ScrapeResponse(BaseModel):
    """Response for course scraping."""
    courses: List[CourseVideos] = Field(default_factory=list)
    total_courses: int = Field(default=0)
    total_videos: int = Field(default=0)


class CoursesListResponse(BaseModel):
    """List of available courses."""
    courses: Dict[str, Dict] = Field(..., description="Available courses")


def get_session() -> requests.Session:
    """Create a requests session with proper headers."""
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def get_page(url: str, session: requests.Session) -> Optional[BeautifulSoup]:
    """Fetch and parse a page."""
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def find_videos(url: str, session: requests.Session) -> List[VideoInfo]:
    """Find all video URLs on a page."""
    soup = get_page(url, session)
    if not soup:
        return []
    
    videos = []
    html = str(soup)
    seen_urls = set()
    
    def add_video(video_url: str, video_type: str, source: str):
        if video_url not in seen_urls:
            seen_urls.add(video_url)
            videos.append(VideoInfo(url=video_url, type=video_type, source=source))
    
    # 1. JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            if data.get("@type") == "VideoObject":
                content_url = data.get("contentUrl", "")
                if ".mp4" in content_url:
                    add_video(content_url, "direct", "hubspot")
        except:
            pass
    
    # 2. Direct HubSpot MP4 links
    for mp4 in re.findall(r'(https://[^"\s]+hubspotusercontent[^"\s]+\.mp4)', html):
        add_video(mp4, "direct", "hubspot")
    
    # 3. contentUrl in scripts
    for cu in re.findall(r'"contentUrl"\s*:\s*"([^"]+\.mp4[^"]*)"', html):
        add_video(cu, "direct", "hubspot")
    
    # 4. HubSpot video embeds
    for iframe in soup.find_all("iframe"):
        hsv = iframe.get("data-hsv-src") or ""
        if "hubspotvideo" in hsv:
            add_video(hsv, "embed", "hubspot-embed")
    
    # 5. Wistia embeds
    for wid in re.findall(r'wistia_async_(\w+)', html):
        add_video(f"https://fast.wistia.net/embed/iframe/{wid}", "embed", "wistia")
    
    # 6. Generic iframe embeds (Vimeo, YouTube, etc.)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        if "vimeo" in src:
            add_video(src, "embed", "vimeo")
        elif "youtube" in src or "youtu.be" in src:
            add_video(src, "embed", "youtube")
        elif "wistia" in src:
            add_video(src, "embed", "wistia")
    
    return videos


def discover_money_pages(session: requests.Session) -> List[str]:
    """Auto-discover pages in the money models course."""
    soup = get_page(f"{BASE_URL}/training/money/context", session)
    if not soup:
        return []
    
    found = []
    for link in soup.find_all("a", href=re.compile(r"/training/money/")):
        href = link.get("href", "").split("?")[0]
        if href and href not in found:
            found.append(href)
    return found


def scrape_course(course_key: str, session: requests.Session) -> Optional[CourseVideos]:
    """Scrape all videos from a single course."""
    if course_key not in COURSES:
        return None
    
    course = COURSES[course_key]
    course_pages = list(course["pages"])
    
    # Auto-discover additional pages for money course
    if course.get("auto_discover") and course_key == "money":
        for p in discover_money_pages(session):
            if p not in course_pages:
                course_pages.append(p)
    
    pages_with_videos = []
    total_videos = 0
    
    for idx, page_path in enumerate(course_pages, 1):
        url = BASE_URL + page_path if page_path.startswith("/") else page_path
        slug = page_path.split("/")[-1]
        
        logger.info(f"Scraping [{idx}/{len(course_pages)}] {slug}")
        
        videos = find_videos(url, session)
        
        # Generate suggested filename
        suffix = "" if len(videos) <= 1 else "-part1"
        suggested_filename = f"{idx:02d}-{slug}{suffix}.mp4"
        
        pages_with_videos.append(PageVideos(
            page_url=url,
            slug=slug,
            index=idx,
            videos=videos,
            suggested_filename=suggested_filename
        ))
        
        total_videos += len(videos)
    
    return CourseVideos(
        course_key=course_key,
        course_name=course["name"],
        total_pages=len(course_pages),
        total_videos=total_videos,
        pages=pages_with_videos
    )


def scrape_all_courses(course_keys: Optional[List[str]] = None) -> ScrapeResponse:
    """
    Scrape videos from all or specified courses.
    
    Args:
        course_keys: List of course keys to scrape. If None, scrapes all.
    """
    session = get_session()
    
    keys_to_scrape = course_keys or list(COURSES.keys())
    courses = []
    total_videos = 0
    
    for key in keys_to_scrape:
        if key in COURSES:
            course_data = scrape_course(key, session)
            if course_data:
                courses.append(course_data)
                total_videos += course_data.total_videos
    
    return ScrapeResponse(
        courses=courses,
        total_courses=len(courses),
        total_videos=total_videos
    )


def get_flat_video_list(course_keys: Optional[List[str]] = None) -> List[Dict]:
    """
    Get a flat list of all videos for easy n8n processing.
    
    Returns list of dicts with:
    - video_url: Direct download URL
    - course_name: Folder name for organization
    - filename: Suggested filename
    - page_url: Source page
    - video_type: direct or embed
    - source: hubspot, wistia, etc.
    """
    scrape_result = scrape_all_courses(course_keys)
    
    videos = []
    for course in scrape_result.courses:
        for page in course.pages:
            for i, video in enumerate(page.videos):
                # Handle multiple videos per page
                if len(page.videos) > 1:
                    filename = f"{page.index:02d}-{page.slug}-part{i+1}.mp4"
                else:
                    filename = f"{page.index:02d}-{page.slug}.mp4"
                
                videos.append({
                    "video_url": video.url,
                    "course_name": course.course_name,
                    "filename": filename,
                    "page_url": page.page_url,
                    "video_type": video.type,
                    "source": video.source,
                    "course_key": course.course_key,
                    "page_index": page.index,
                    "page_slug": page.slug
                })
    
    return videos


__all__ = [
    "COURSES",
    "scrape_course",
    "scrape_all_courses",
    "get_flat_video_list",
    "ScrapeResponse",
    "CourseVideos",
    "PageVideos",
    "VideoInfo",
    "CoursesListResponse"
]
