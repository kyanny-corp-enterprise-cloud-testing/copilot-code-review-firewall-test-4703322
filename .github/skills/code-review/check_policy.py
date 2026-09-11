import json
from pathlib import Path
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shipping import qualifies_for_free_shipping


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def main():
    try:
        config = json.loads((ROOT / "policy-endpoint.json").read_text())
        endpoint = config["url"]
        parts = urlsplit(endpoint)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Use an HTTPS URL without credentials, query, or fragment")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"CONFIG_ERROR {error}", flush=True)
        return 4

    probe_id = uuid.uuid4().hex
    request_url = endpoint + "?" + urlencode({"probe_id": probe_id})
    print(f"REQUEST_START probe_id={probe_id} url={request_url}", flush=True)
    request = Request(request_url, headers={
        "ngrok-skip-browser-warning": "1",
        "Cache-Control": "no-cache",
        "User-Agent": "ccr-firewall-probe/1.0",
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            payload = response.read(65537)
            http_status = response.status
    except HTTPError as error:
        print(f"FETCH_ERROR probe_id={probe_id} http_status={error.code}", flush=True)
        error.close()
        print("An HTTP error alone does not prove a Copilot firewall block.")
        return 2
    except (URLError, OSError) as error:
        print(f"FETCH_ERROR probe_id={probe_id} error={error}", flush=True)
        print("A connection error alone does not prove a Copilot firewall block.")
        return 2

    print(f"HTTP_RESPONSE probe_id={probe_id} status={http_status}", flush=True)
    try:
        if http_status != 200 or len(payload) > 65536:
            raise ValueError("Expected HTTP 200 and at most 65536 bytes")
        policy = json.loads(payload)
        minimum = policy["free_shipping_minimum"]
        if type(minimum) is not int or minimum < 1:
            raise ValueError("free_shipping_minimum must be a positive integer")
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        print(f"POLICY_ERROR probe_id={probe_id} error={error}", flush=True)
        return 3

    print(f"POLICY_FETCH_OK probe_id={probe_id} free_shipping_minimum={minimum}", flush=True)
    mismatches = []
    for order_total, expected in ((minimum - 1, False), (minimum, True), (minimum + 1, True)):
        actual = qualifies_for_free_shipping(order_total)
        print(f"CASE order_total={order_total} expected={expected} actual={actual}")
        if actual != expected:
            mismatches.append(order_total)
    if mismatches:
        print(f"POLICY_MISMATCH order_totals={mismatches}", flush=True)
        return 1
    print("POLICY_MATCH", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())