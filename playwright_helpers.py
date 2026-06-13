from __future__ import annotations

from typing import Callable, Iterable, Optional, Tuple

from playwright.sync_api import Browser, Playwright


def launch_browser(
    p: Playwright,
    *,
    headless: bool,
    preferred_engines: Iterable[str],
    log: Optional[Callable[[str], None]] = None,
    launch_kwargs: Optional[dict] = None,
) -> Tuple[str, Browser]:
    """
    Launch a Playwright browser using the first available engine from `preferred_engines`.

    Why this exists:
    - Some sites block Chromium in headless mode (HTTP 403). On macOS, WebKit/Firefox
      can sometimes work headless where Chromium doesn't.
    - Users may not have all browsers installed; we fall back gracefully with a clear log.
    """

    kwargs = dict(launch_kwargs or {})

    last_error: Optional[BaseException] = None
    for engine in preferred_engines:
        browser_type = getattr(p, engine, None)
        if browser_type is None:
            continue
        try:
            browser = browser_type.launch(headless=headless, **kwargs)
            if log:
                log(f"Browser engine: {engine} (headless={headless})")
            return engine, browser
        except BaseException as e:
            last_error = e
            if log:
                log(f"Could not launch {engine}: {e}")

    hint = (
        "If you recently updated Playwright, you may need to download browsers:\n"
        "  python3 -m playwright install\n"
        "For Naukri headless specifically:\n"
        "  python3 -m playwright install webkit firefox\n"
    )
    raise RuntimeError(f"Could not launch any browser. Last error: {last_error}\n\n{hint}")

