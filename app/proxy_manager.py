import logging
import os
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)


def get_proxy_url() -> Optional[str]:
    """Load proxy URL from file or environment"""
    # Check environment first
    env_proxy = os.environ.get('PROXY_URL')
    if env_proxy:
        return env_proxy.strip()
    
    # Check file locations
    locations = [
        Path('/tmp/proxies.txt'),
        Path('/app/proxies.txt'),
        Path(__file__).parent.parent / 'proxies.txt',
        Path(__file__).parent / 'proxies.txt',
    ]
    
    # Copy read-only to writable location if needed
    ro_proxy = Path('/app/proxies.txt')
    writable_proxy = Path('/tmp/proxies.txt')
    
    if ro_proxy.exists() and not writable_proxy.exists():
        try:
            import shutil
            shutil.copy(ro_proxy, writable_proxy)
            logger.info(f"Copied proxies.txt to writable location: {writable_proxy}")
        except Exception as e:
            logger.warning(f"Failed to copy proxies.txt: {e}")
    
    for loc in locations:
        if loc.exists():
            try:
                content = loc.read_text().strip()
                if content and not content.startswith('#'):
                    # Ensure http:// prefix
                    if not content.startswith('http://') and not content.startswith('https://'):
                        content = f"http://{content}"
                    logger.info(f"Loaded proxy from: {loc}")
                    return content
            except Exception as e:
                logger.warning(f"Failed to read {loc}: {e}")
    
    return None


class ProxyManager:
    def __init__(self):
        self.proxy_url = get_proxy_url()
        if self.proxy_url:
            logger.info(f"ProxyManager initialized with proxy: {self._mask_proxy_url(self.proxy_url)}")
        else:
            logger.warning("No proxy configured - requests will use direct connection")

    def _mask_proxy_url(self, url: str) -> str:
        """Mask credentials in proxy URL for logging"""
        if '@' in url:
            prefix = url.split('://')[0]
            host_part = url.split('@')[-1]
            return f"{prefix}://***:***@{host_part}"
        return url

    def get_proxy(self) -> Optional[Dict[str, str]]:
        """Get the configured proxy"""
        if self.proxy_url:
            return {
                "http": self.proxy_url,
                "https": self.proxy_url,
            }
        return None

    def get_proxies_for_retry(self, count: int = 3) -> List[Optional[Dict[str, str]]]:
        """
        Get proxies for retry attempts.
        With residential proxy: [proxy, proxy, proxy, direct]
        Without proxy: [direct]
        """
        proxies = []
        
        if self.proxy_url:
            # Residential proxies rotate IPs automatically, so we can retry with same URL
            for _ in range(count):
                proxies.append({
                    "http": self.proxy_url,
                    "https": self.proxy_url,
                })
        
        # Always include direct connection as last fallback
        proxies.append(None)
        
        return proxies

    def mark_proxy_failed(self, proxy_url: str):
        """For residential proxies, we don't mark as failed since IPs rotate"""
        logger.debug(f"Proxy request failed (IP will rotate): {self._mask_proxy_url(proxy_url)}")

    def get_stats(self) -> dict:
        """Get proxy configuration status"""
        return {
            "proxy_configured": bool(self.proxy_url),
            "proxy_type": "residential" if self.proxy_url else "none",
            "proxy_url": self._mask_proxy_url(self.proxy_url) if self.proxy_url else None,
        }


# Global instance
proxy_manager = ProxyManager()
