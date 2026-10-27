"""A tiny JSON-over-HTTP client with retries. Standard library only."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .provider_base import ProviderError

RETRY_CODES = (429, 502, 503, 504)


def build_url(base, path, params=None):
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)
    return url


def request_json(method, url, headers=None, body=None, timeout=30, retries=3, explain=None):
    """Send a request and return parsed JSON (or None for an empty body).

    explain: optional function(status, url) -> str that turns an HTTP status into
    a helpful sentence for the user.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})

    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as e:
            if e.code in RETRY_CODES and attempt < retries:
                wait = e.headers.get("Retry-After") if e.headers else None
                try:
                    delay = min(float(wait), 30.0) if wait else 2.0 ** attempt
                except ValueError:
                    delay = 2.0 ** attempt
                time.sleep(delay)
                attempt += 1
                continue
            detail = _error_detail(e)
            hint = explain(e.code, url) if explain else ""
            msg = "%s %s returned %s." % (method, _strip_query(url), e.code)
            if hint:
                msg += " " + hint
            if detail:
                msg += " Server said: " + detail
            raise ProviderError(msg, status=e.code)
        except urllib.error.URLError as e:
            raise ProviderError("Cannot reach %s (%s). Check the URL and your network." % (_strip_query(url), e.reason))
        except (TimeoutError, OSError) as e:
            if attempt < retries:
                time.sleep(2.0 ** attempt)
                attempt += 1
                continue
            raise ProviderError("Request to %s failed: %s" % (_strip_query(url), e))


def _strip_query(url):
    return url.split("?", 1)[0]


def _error_detail(err):
    try:
        raw = err.read().decode("utf-8", "replace")
    except Exception:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw.strip()[:200]
    msgs = []
    if isinstance(data, dict):
        msgs.extend(str(m) for m in data.get("errorMessages") or [])
        errors = data.get("errors")
        if isinstance(errors, dict):
            msgs.extend("%s: %s" % (k, v) for k, v in errors.items())
        if data.get("message"):
            msgs.append(str(data["message"]))
    return "; ".join(msgs)[:300]
