from ipaddress import ip_address
from urllib.parse import urlparse


MULTI_PART_SUFFIXES = {
    "ac.uk",
    "co.in",
    "co.jp",
    "co.kr",
    "co.nz",
    "co.uk",
    "co.za",
    "com.au",
    "com.br",
    "com.cn",
    "com.mx",
    "com.sg",
    "net.au",
    "org.au",
    "org.uk",
}

SHARED_HOST_SUFFIXES = {
    "github.io",
    "netlify.app",
    "pages.dev",
    "vercel.app",
}


def source_domain_family(url: str) -> str:
    """Return a conservative publisher family for source-independence checks."""
    host = (urlparse(str(url)).hostname or "").lower().removeprefix("www.").rstrip(".")
    if not host:
        return ""
    try:
        ip_address(host)
        return host
    except ValueError:
        pass

    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    suffix = ".".join(labels[-2:])
    if suffix in MULTI_PART_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    if suffix in SHARED_HOST_SUFFIXES:
        return ".".join(labels[-3:])
    return suffix
