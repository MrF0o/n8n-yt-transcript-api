import requests
import random
import logging
import time
import threading
from typing import Optional, Dict, List
from collections import deque

logger = logging.getLogger(__name__)

# Multiple proxy sources for better coverage
PROXY_LIST_URLS = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
]

# Video ID known to have transcripts - used for validation
TEST_VIDEO_ID = "dQw4w9WgXcQ"  # Rick Astley - Never Gonna Give You Up


class ProxyManager:
    def __init__(self):
        # Raw proxy list from source
        self.raw_proxies: list[str] = []
        self.last_fetch = 0
        self.fetch_interval = 1800  # Refresh list every 30 min (more aggressive)
        
        # Ready-to-use validated proxies (fast access)
        self.ready_proxies: deque[str] = deque(maxlen=30)  # Smaller pool, higher quality
        
        # Track failed proxies to avoid retrying them
        self.failed_proxies: set[str] = set()
        self.failed_proxies_lock = threading.Lock()
        
        # Background validation
        self.validation_lock = threading.Lock()
        self.is_validating = False
        self.min_ready_proxies = 5  # Trigger background refresh when below this
        
        # Start background worker
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._background_worker, daemon=True)
        self._worker_thread.start()
        
        logger.info("ProxyManager initialized with deep transcript validation")

    def _background_worker(self):
        """Background thread that keeps the proxy pool filled"""
        # Initial fetch and validation
        time.sleep(1)  # Small delay to let app start
        self._refresh_proxy_pool()
        
        while not self._stop_event.is_set():
            try:
                # Check if we need more proxies
                if len(self.ready_proxies) < self.min_ready_proxies:
                    logger.info(f"Ready proxies low ({len(self.ready_proxies)}), validating more...")
                    self._validate_batch()
                
                # Check if we need to refresh the raw list
                if time.time() - self.last_fetch > self.fetch_interval:
                    logger.info("Proxy list expired, refreshing...")
                    self._refresh_proxy_pool()
                
                # Sleep before next check
                self._stop_event.wait(timeout=30)
            except Exception as e:
                logger.error(f"Background worker error: {e}")
                self._stop_event.wait(timeout=60)

    def _fetch_raw_proxies(self) -> bool:
        """Fetch raw proxy list from multiple sources"""
        all_proxies = set()
        
        for url in PROXY_LIST_URLS:
            try:
                logger.info(f"Fetching proxy list from {url}...")
                response = requests.get(url, timeout=15)
                if response.status_code == 200:
                    lines = response.text.strip().split('\n')
                    proxies = [line.strip() for line in lines if line.strip() and ':' in line]
                    all_proxies.update(proxies)
                    logger.info(f"Fetched {len(proxies)} proxies from {url}")
            except Exception as e:
                logger.warning(f"Failed to fetch from {url}: {e}")
        
        if all_proxies:
            self.raw_proxies = list(all_proxies)
            self.last_fetch = time.time()
            # Clear failed proxies on fresh fetch (they might work now)
            with self.failed_proxies_lock:
                self.failed_proxies.clear()
            logger.info(f"Total unique proxies fetched: {len(self.raw_proxies)}")
            return True
        
        logger.error("Failed to fetch proxies from any source")
        return False

    def _validate_proxy(self, proxy_addr: str) -> bool:
        """Deep validation - actually test if proxy can fetch YouTube transcripts"""
        proxies = {
            "http": f"http://{proxy_addr}",
            "https": f"http://{proxy_addr}",
        }
        try:
            # Import here to avoid circular imports
            from youtube_transcript_api import YouTubeTranscriptApi
            from youtube_transcript_api.proxies import GenericProxyConfig
            
            proxy_config = GenericProxyConfig(
                http_url=proxies['http'],
                https_url=proxies['https'],
            )
            ytt_api = YouTubeTranscriptApi(proxy_config=proxy_config)
            
            # Actually try to list transcripts - this is the real test
            transcript_list = ytt_api.list(TEST_VIDEO_ID)
            
            # If we got here without error, the proxy works for YouTube transcripts
            logger.debug(f"Proxy {proxy_addr} validated successfully (can fetch transcripts)")
            return True
            
        except Exception as e:
            logger.debug(f"Proxy {proxy_addr} failed transcript validation: {type(e).__name__}")
            return False

    def _validate_batch(self, batch_size: int = 30):
        """Validate a batch of proxies and add working ones to ready pool"""
        with self.validation_lock:
            if self.is_validating:
                return
            self.is_validating = True
        
        try:
            if not self.raw_proxies:
                self._fetch_raw_proxies()
            
            if not self.raw_proxies:
                return
            
            # Get candidates (not already ready, not failed)
            ready_set = set(self.ready_proxies)
            with self.failed_proxies_lock:
                failed_set = self.failed_proxies.copy()
            
            candidates = [
                p for p in self.raw_proxies 
                if p not in ready_set and p not in failed_set
            ]
            
            if not candidates:
                # All proxies tried, clear failed to retry
                logger.info("All proxies tried, clearing failed list for retry")
                with self.failed_proxies_lock:
                    self.failed_proxies.clear()
                candidates = [p for p in self.raw_proxies if p not in ready_set]
            
            # Sample random candidates
            batch = random.sample(candidates, min(len(candidates), batch_size))
            
            validated = 0
            for proxy in batch:
                max_len = self.ready_proxies.maxlen or 30
                if len(self.ready_proxies) >= max_len:
                    break
                    
                if self._validate_proxy(proxy):
                    self.ready_proxies.append(proxy)
                    validated += 1
                    logger.debug(f"Validated proxy: {proxy}")
                else:
                    with self.failed_proxies_lock:
                        self.failed_proxies.add(proxy)
            
            if validated > 0:
                logger.info(f"Added {validated} proxies to ready pool (total: {len(self.ready_proxies)})")
                
        finally:
            with self.validation_lock:
                self.is_validating = False

    def _refresh_proxy_pool(self):
        """Full refresh: fetch new list and validate initial batch"""
        self._fetch_raw_proxies()
        self._validate_batch(batch_size=50)

    def get_proxy(self) -> Optional[Dict[str, str]]:
        """
        Get a ready proxy instantly from the pool.
        Returns None if no proxies available (fallback to direct connection).
        """
        if self.ready_proxies:
            # Rotate: take from front, will be re-added if still working
            proxy = self.ready_proxies[0]
            # Rotate the deque so we use different proxies
            self.ready_proxies.rotate(-1)
            return {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}",
            }
        
        # No ready proxies - trigger async validation but don't block
        if not self.is_validating:
            threading.Thread(target=self._validate_batch, daemon=True).start()
        
        return None

    def get_proxies_for_retry(self, count: int = 3) -> List[Optional[Dict[str, str]]]:
        """
        Get multiple proxies for retry attempts.
        Returns a list that includes None as last item (for direct connection fallback).
        """
        proxies = []
        seen = set()
        
        # Get unique proxies from the pool
        for _ in range(min(count, len(self.ready_proxies))):
            if self.ready_proxies:
                proxy = self.ready_proxies[0]
                self.ready_proxies.rotate(-1)
                if proxy not in seen:
                    seen.add(proxy)
                    proxies.append({
                        "http": f"http://{proxy}",
                        "https": f"http://{proxy}",
                    })
        
        # Always include direct connection as last fallback
        proxies.append(None)
        
        return proxies

    def mark_proxy_failed(self, proxy_url: str):
        """Mark a proxy as failed (called when a request fails)"""
        # Extract ip:port from URL like "http://1.2.3.4:8080"
        try:
            proxy_addr = proxy_url.replace("http://", "").replace("https://", "")
            with self.failed_proxies_lock:
                self.failed_proxies.add(proxy_addr)
            
            # Remove from ready pool
            try:
                self.ready_proxies.remove(proxy_addr)
                logger.info(f"Removed failed proxy: {proxy_addr}")
            except ValueError:
                pass
        except Exception as e:
            logger.debug(f"Error marking proxy failed: {e}")

    def get_stats(self) -> dict:
        """Get current proxy pool statistics"""
        return {
            "ready_proxies": len(self.ready_proxies),
            "raw_proxies": len(self.raw_proxies),
            "failed_proxies": len(self.failed_proxies),
            "last_fetch_ago": int(time.time() - self.last_fetch) if self.last_fetch else None,
        }


# Global instance
proxy_manager = ProxyManager()
