import json
import os
from collections import Counter
from datetime import datetime, timezone
from hashlib import md5
from typing import Any, Dict, List, Optional

import tldextract

from client.trackers.reads import CookieReadInterceptor

from .trackers import TrackerList

EMPTY_COOKIE: str = "<empty>"


class Outfile:
    def __init__(
        self,
        dir: str = "./cookie_data/",
        name: str = "default",
        target_url: str = "",
    ):
        self.dir = dir
        self.name = name
        self.target_url = target_url

    @property
    def path(self) -> str:
        return os.path.join(self.dir, self.name)


class OutputFormat:
    @staticmethod
    def process_and_save(
        cookies: List[Dict[str, Any]],
        cookie_set_context: Dict[tuple[str, str], Any],
        request_log: List[Dict[str, Any]],
        output: Outfile,
        tracker_list: Optional[TrackerList] = None,
        cookie_read_interceptor: Optional[CookieReadInterceptor] = None,
        sensitivity_result: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        now_ts = now.timestamp()

        cookies_metadata = []
        num_session = 0
        num_persistent = 0
        num_trackers = 0
        lifetime_values = []

        for cookie in cookies:
            is_session = cookie.get("session", False)
            expires = cookie.get("expires", -1)
            cookie_domain = cookie.get("domain", "")
            cookie_name = cookie.get("name", "")

            registered = (
                tldextract.extract(cookie_domain).registered_domain or cookie_domain
            )

            if is_session or expires == -1:
                num_session += 1
                cookie_type = "session"
                expires_at = None
                lifetime_days = None
            else:
                num_persistent += 1
                cookie_type = "persistent"
                expires_at = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()
                lifetime_days = (expires - now_ts) / 86400
                if lifetime_days >= 0:
                    lifetime_values.append(lifetime_days)

            tracker_detection = None
            if tracker_list is not None:
                tracker_detection = tracker_list.is_tracker(cookie)
                if tracker_detection:
                    num_trackers += 1

            network_context = cookie_set_context.get((cookie_name, registered), {})
            set_by_url = network_context.get("set_by_request_url")
            ep_for_cookie = None
            if set_by_url:
                match = next((r for r in request_log if r["url"] == set_by_url), None)
                if match:
                    ep_for_cookie = match.get("easyprivacy")

            single_cookie_metadata = {
                "name": cookie_name,
                "domain": cookie_domain,
                "session": is_session,
                "cookie_type": cookie_type,
                "secure": cookie.get("secure"),
                "httpOnly": cookie.get("httpOnly"),
                "sameSite": cookie.get("sameSite"),
                "expires_at": expires_at,
                "lifetime_days": lifetime_days,
                "set_by": {
                    "url": network_context.get("set_by_request_url"),
                    "type": network_context.get("set_by_request_type"),
                    "initiator": network_context.get("set_by_initiator"),
                    "third_party": network_context.get("is_third_party_set"),
                    "easyprivacy": ep_for_cookie or {"matched": False},
                },
                "md5_value": md5(
                    cookie.get("value", EMPTY_COOKIE).encode()
                ).hexdigest(),
                "is_tracker": tracker_detection.to_dict() if tracker_detection else None,
            }

            cookies_metadata.append(single_cookie_metadata)

        avg_lifetime_days = (
            sum(lifetime_values) / len(lifetime_values) if lifetime_values else None
        )

        total_requests = len(request_log)
        ep_matched_requests = [
            r for r in request_log if (r.get("easyprivacy") or {}).get("matched")
        ]
        num_ep_requests = len(ep_matched_requests)
        blocked_domains = Counter(
            tldextract.extract(r["url"]).registered_domain
            for r in ep_matched_requests
            if r["url"]
        )

        site_metadata = {
            "collection_timestamp": now.isoformat(),
            "total_cookies": len(cookies_metadata),
            "num_session": num_session,
            "num_persistent": num_persistent,
            "avg_lifetime_days": avg_lifetime_days,
            "min_lifetime_days": min(lifetime_values) if lifetime_values else None,
            "max_lifetime_days": max(lifetime_values) if lifetime_values else None,
            "total_requests": total_requests,
            "num_easyprivacy_requests": num_ep_requests,
            "pct_easyprivacy_requests": (
                round(num_ep_requests / total_requests * 100, 1)
                if total_requests
                else 0.0
            ),
            "outgoing_ep_requests": [
                {"domain": domain, "count": count}
                for domain, count in blocked_domains.most_common(100)
            ],
            "sensitivity": sensitivity_result
        }

        if tracker_list is not None:
            site_metadata["num_trackers"] = num_trackers
            site_metadata["pct_trackers"] = (
                round(num_trackers / len(cookies_metadata) * 100, 1)
                if cookies_metadata
                else 0.0
            )

        output_data: Dict[str, Any] = {
            "target_url": output.target_url,
            "site_metadata": site_metadata,
            "cookies": cookies_metadata,
        }

        if cookie_read_interceptor is not None:
            output_data["cookie_reads"] = cookie_read_interceptor.session.to_dict()

        if output.dir:
            os.makedirs(output.dir, exist_ok=True)
            output_path = os.path.join(output.dir, output.name)
        else:
            output_path = output.name

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4)
