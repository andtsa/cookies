from abc import ABC, abstractmethod
from typing import Callable, Dict, Any


class Client(ABC):
    """
    Abstract base class defining the interface for browser automation clients.
    
    Provides a contract for setting up browsers, navigating to pages, 
    executing behaviors, and handling cleanup with custom callbacks.
    """
    
    @abstractmethod
    async def visitPage(
        self, 
        url: str, 
        behavior: Callable, 
        on_close: Callable, 
        params: Dict[str, Any], 
        output_args: Dict[str, Any]
    ) -> None:
        """
        Orchestrate a complete page visit workflow.
        
        Args:
            url: The target URL to visit
            behavior: Callback function to execute after page load (e.g., waiting, clicking)
            on_close: Callback function to execute before closing browser (e.g., snapshot data)
            params: Parameters to pass to the behavior callback
            output_args: Arguments to pass to the on_close callback
        """
        pass
    
    @abstractmethod
    async def _setup(self) -> None:
        """
        Initialize the browser, context, and any required sessions.
        
        This should handle:
        - Launching the browser
        - Creating browser context and page
        - Establishing any protocol connections (e.g., CDP)
        - Enabling necessary domains
        - Clearing initial state (e.g., cookies)
        """
        pass
    
    @abstractmethod
    async def _navigate_to_page(self, url: str) -> None:
        """
        Navigate to the specified URL.
        
        Args:
            url: The target URL to navigate to
        """
        pass
    
    @abstractmethod
    async def _behavior_non_interactive(self, milliseconds: int) -> None:
        """
        Execute a passive wait behavior (non-interactive).
        
        Args:
            milliseconds: Duration to wait in milliseconds
        """
        pass
    
    @abstractmethod
    async def _on_close_get_cookies_snapshot(
        self, 
        output_dir: str, 
        output_name: str, 
        params: Dict[str, Any]
    ) -> None:
        """
        Capture cookies and write to JSON file before closing browser.
        
        Args:
            output_dir: Directory to save the output file
            output_name: Name of the output file
            params: Additional metadata to include in the output JSON
        """
        pass
    
    @abstractmethod
    async def _on_close_empty(self) -> None:
        """
        Default cleanup handler that simply closes the browser.
        """
        pass
