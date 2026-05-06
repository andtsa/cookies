from typing import Dict
from enum import Enum
from chromium_client import ChromiumClient
from client import Client


class Browser(Enum):
    """Enumeration of supported browser types."""
    CHROMIUM = "chromium"


class ClientUtils:
    """
    Factory class for instantiating browser automation clients.
    
    Provides a centralized way to create and configure different
    browser clients based on the target browser type.
    """
    
    def __init__(self, browser_paths: Dict[str, str]):
        """
        Initialize ClientUtils with browser paths.
        
        Args:
            browser_paths: Dictionary mapping browser names to executable paths
                          (e.g., {"brave": "C:/Program Files/Brave/brave.exe"})
                          Used for custom browser binaries in future implementations.
        """
        self.browser_paths = browser_paths
    
    def get_client(self, browser_type: Browser) -> Client:
        """
        Get a client instance for the specified browser type.
        
        Args:
            browser_type: The type of browser to instantiate
            
        Returns:
            Client instance for the specified browser
            
        Raises:
            ValueError: If the requested browser type is not supported
        """
        
        if browser_type == Browser.CHROMIUM:
            return ChromiumClient()
        else:
            raise ValueError(f"Unsupported browser type: {browser_type.value}")
