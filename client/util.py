import tldextract


def _registered(domain: str) -> str:
    return tldextract.extract(domain).registered_domain or domain.lstrip(".")


def _parse_set_cookie_name(raw_header: str) -> str | None:
    """Extract the cookie name from a raw Set-Cookie header value."""
    # CDP sometimes concatenates multiple Set-Cookie values with \n
    first = raw_header.split("\n")[0].strip()
    if "=" not in first:
        return None
    return first.split("=")[0].strip() or None
