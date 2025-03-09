import asyncio
import json
from typing import Optional
import base64

from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from app.tool.base import BaseTool, ToolResult


_BROWSER_DESCRIPTION = """
Interact with a web browser to perform various actions such as navigation, element interaction,
content extraction, and tab management. Supported actions include:
- 'navigate': Go to a specific URL
- 'click': Click an element by index
- 'input_text': Input text into an element
- 'screenshot': Capture a screenshot
- 'get_html': Get page HTML content
- 'get_text': Get text content of the page
- 'read_links': Get all links on the page
- 'execute_js': Execute JavaScript code
- 'scroll': Scroll the page
- 'switch_tab': Switch to a specific tab
- 'new_tab': Open a new tab
- 'close_tab': Close the current tab
- 'refresh': Refresh the current page
"""


class BrowserUseTool(BaseTool):
    name: str = "browser_use"
    description: str = _BROWSER_DESCRIPTION
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "navigate",
                    "click",
                    "input_text",
                    "screenshot",
                    "get_html",
                    "get_text",
                    "execute_js",
                    "scroll",
                    "switch_tab",
                    "new_tab",
                    "close_tab",
                    "refresh",
                ],
                "description": "The browser action to perform",
            },
            "url": {
                "type": "string",
                "description": "URL for 'navigate' or 'new_tab' actions",
            },
            "index": {
                "type": "integer",
                "description": "Element index for 'click' or 'input_text' actions",
            },
            "text": {"type": "string", "description": "Text for 'input_text' action"},
            "script": {
                "type": "string",
                "description": "JavaScript code for 'execute_js' action",
            },
            "scroll_amount": {
                "type": "integer",
                "description": "Pixels to scroll (positive for down, negative for up) for 'scroll' action",
            },
            "tab_id": {
                "type": "integer",
                "description": "Tab ID for 'switch_tab' action",
            },
        },
        "required": ["action"],
        "dependencies": {
            "navigate": ["url"],
            "click": ["index"],
            "input_text": ["index", "text"],
            "execute_js": ["script"],
            "switch_tab": ["tab_id"],
            "new_tab": ["url"],
            "scroll": ["scroll_amount"],
        },
    }

    lock: asyncio.Lock = Field(default_factory=asyncio.Lock)
    playwright: Optional[any] = Field(default=None, exclude=True)
    browser: Optional[Browser] = Field(default=None, exclude=True)
    context: Optional[BrowserContext] = Field(default=None, exclude=True)
    page: Optional[Page] = Field(default=None, exclude=True)
    pages: list[Page] = Field(default_factory=list, exclude=True)

    @field_validator("parameters", mode="before")
    def validate_parameters(cls, v: dict, info: ValidationInfo) -> dict:
        if not v:
            raise ValueError("Parameters cannot be empty")
        return v

    async def _ensure_browser_initialized(self) -> Page:
        """Ensure browser and context are initialized."""
        if self.playwright is None:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=False)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
            self.pages = [self.page]
        return self.page

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        index: Optional[int] = None,
        text: Optional[str] = None,
        script: Optional[str] = None,
        scroll_amount: Optional[int] = None,
        tab_id: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """
        Execute a specified browser action.

        Args:
            action: The browser action to perform
            url: URL for navigation or new tab
            index: Element index for click or input actions
            text: Text for input action
            script: JavaScript code for execution
            scroll_amount: Pixels to scroll for scroll action
            tab_id: Tab ID for switch_tab action
            **kwargs: Additional arguments

        Returns:
            ToolResult with the action's output or error
        """
        async with self.lock:
            try:
                page = await self._ensure_browser_initialized()

                if action == "navigate":
                    if not url:
                        return ToolResult(error="URL is required for 'navigate' action")
                    await page.goto(url)
                    return ToolResult(output=f"Navigated to {url}")

                elif action == "click":
                    if index is None:
                        return ToolResult(error="Index is required for 'click' action")
                    elements = await page.query_selector_all("*")
                    if index >= len(elements):
                        return ToolResult(error=f"Element with index {index} not found")
                    await elements[index].click()
                    return ToolResult(output=f"Clicked element at index {index}")

                elif action == "input_text":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'input_text' action"
                        )
                    elements = await page.query_selector_all("*")
                    if index >= len(elements):
                        return ToolResult(error=f"Element with index {index} not found")
                    await elements[index].fill(text)
                    return ToolResult(
                        output=f"Input '{text}' into element at index {index}"
                    )

                elif action == "screenshot":
                    screenshot = await page.screenshot(full_page=True)
                    screenshot_base64 = base64.b64encode(screenshot).decode()
                    return ToolResult(
                        output=f"Screenshot captured (base64 length: {len(screenshot_base64)})",
                        system=screenshot_base64,
                    )

                elif action == "get_html":
                    html = await page.content()
                    truncated = html[:2000] + "..." if len(html) > 2000 else html
                    return ToolResult(output=truncated)

                elif action == "get_text":
                    text = await page.evaluate("document.body.innerText")
                    return ToolResult(output=text)

                elif action == "read_links":
                    links = await page.evaluate("""
                        Array.from(document.querySelectorAll('a[href]'))
                            .filter(elem => elem.innerText)
                            .map(elem => `${elem.innerText}: ${elem.href}`)
                            .join('\\n')
                    """)
                    return ToolResult(output=links)

                elif action == "execute_js":
                    if not script:
                        return ToolResult(
                            error="Script is required for 'execute_js' action"
                        )
                    result = await page.evaluate(script)
                    return ToolResult(output=str(result))

                elif action == "scroll":
                    if scroll_amount is None:
                        return ToolResult(
                            error="Scroll amount is required for 'scroll' action"
                        )
                    await page.evaluate(f"window.scrollBy(0, {scroll_amount});")
                    direction = "down" if scroll_amount > 0 else "up"
                    return ToolResult(
                        output=f"Scrolled {direction} by {abs(scroll_amount)} pixels"
                    )

                elif action == "switch_tab":
                    if tab_id is None:
                        return ToolResult(
                            error="Tab ID is required for 'switch_tab' action"
                        )
                    if tab_id >= len(self.pages):
                        return ToolResult(error=f"Tab {tab_id} does not exist")
                    self.page = self.pages[tab_id]
                    return ToolResult(output=f"Switched to tab {tab_id}")

                elif action == "new_tab":
                    if not url:
                        return ToolResult(error="URL is required for 'new_tab' action")
                    new_page = await self.context.new_page()
                    await new_page.goto(url)
                    self.pages.append(new_page)
                    self.page = new_page
                    return ToolResult(output=f"Opened new tab with URL {url}")

                elif action == "close_tab":
                    if len(self.pages) <= 1:
                        return ToolResult(error="Cannot close the last tab")
                    current_index = self.pages.index(self.page)
                    await self.page.close()
                    self.pages.remove(self.page)
                    self.page = self.pages[max(0, current_index - 1)]
                    return ToolResult(output="Closed current tab")

                elif action == "refresh":
                    await page.reload()
                    return ToolResult(output="Refreshed current page")

                else:
                    return ToolResult(error=f"Unknown action: {action}")

            except Exception as e:
                return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")

    async def get_current_state(self) -> ToolResult:
        """Get the current browser state as a ToolResult."""
        async with self.lock:
            try:
                page = await self._ensure_browser_initialized()
                state = {
                    "url": page.url,
                    "title": await page.title(),
                    "num_tabs": len(self.pages),
                    "current_tab": self.pages.index(self.page),
                }
                return ToolResult(output=json.dumps(state, indent=2))
            except Exception as e:
                return ToolResult(error=f"Failed to get browser state: {str(e)}")

    async def cleanup(self):
        """Clean up browser resources."""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        self.context = None
        self.page = None
        self.pages = []

    def __del__(self):
        """Ensure cleanup on object destruction."""
        if self.browser or self.playwright:
            asyncio.create_task(self.cleanup())
