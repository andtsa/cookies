class TrackerUtil:
    """
    Collects and (eventually) normalises network events from any browser engine.

    CDP events (Chromium) arrive as raw dicts; Playwright events (Firefox/WebKit)
    arrive as Request/Response objects. Normalization by caller type will be
    implemented here when the stubs are filled in.
    """

    def on_request_sent(self, event) -> None:
        pass

    def on_response_extra(self, event) -> None:
        pass
