import asyncio
from typing import Dict, Any, Optional
from client_utils import ClientUtils, Browser


async def run_for_page(
    url: str,
    wait_time_ms: int,
    output_dir: str,
    output_name: str,
    browser: Browser,
    params: Dict[str, Any],
    timeout_ms: Optional[int] = 10000,
    headless: Optional[bool] = False
) -> None:
    """
    Execute a page visit workflow with specified browser and behavior.
    
    Args:
        url: Target URL to visit
        wait_time_ms: Time to wait on page in milliseconds
        output_dir: Directory to save output file (empty string for current dir)
        output_name: Name of output file
        browser: Browser type to use (from Browser enum)
        params: Additional metadata to include in output JSON
    """
    client_utils = ClientUtils(browser_paths={})
    client = client_utils.get_client(browser)
    
    async def behavior_callback(client_instance, behavior_params):
        await client_instance._behavior_non_interactive(behavior_params['wait_time_ms'])
    
    async def on_close_callback(client_instance, close_args):
        await client_instance._on_close_get_cookies_snapshot(
            output_dir=close_args['output_dir'],
            output_name=close_args['output_name'],
            params=close_args['params']
        )
    
    try:
        await client.visit_page(
            url=url,
            behavior=behavior_callback,
            on_close=on_close_callback,
            params={'wait_time_ms': wait_time_ms},
            output_args={
                'output_dir': output_dir,
                'output_name': output_name,
                'params': params
            },
            timeout_ms=timeout_ms,
            headless=headless
        )
    except Exception as e:
        print(f"Error during page visit: {e}")
        await client._on_close_empty()


async def main():
    target_url = 'https://www.nytimes.com'
    wait_time_seconds = 20
    output_file = 'nyt.json'
    
    wait_time_ms = wait_time_seconds * 1000
    
    #  metadata to include in output
    params = {
        'target_url': target_url,
        'wait_time_seconds': wait_time_seconds
    }
    await run_for_page(
        url=target_url,
        wait_time_ms=wait_time_ms,
        output_dir='cookies_data',
        output_name=output_file,
        browser=Browser.CHROMIUM,
        params=params,
        timeout_ms=10000,
        headless=False
    )


if __name__ == '__main__':
    asyncio.run(main())