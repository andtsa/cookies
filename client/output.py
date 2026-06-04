import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import tldextract

from client.trackers.js import CookieReadInterceptor

from .trackers import TrackerList

EMPTY_COOKIE: str = "<empty>"


class Outfile:
    def __init__(
        self,
        dir: str = "./cookie_data/",
        name: str = "default",
        target_url: str = "",
        country: str = "unknown",
        browser: str = "unknown",
        rank: Optional[int] = None,
        category: Optional[str] = None,
    ):
        self.dir = dir
        self.name = name
        self.target_url = target_url
        self.country = country
        self.browser = browser
        self.rank = rank
        self.category = category

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

        cookies_out = []
        num_session = 0
        num_persistent = 0
        num_trackers = 0

        # map name to first js write event for attribution
        js_writes_by_name: dict[str, Any] = {}
        if cookie_read_interceptor is not None:
            for w in cookie_read_interceptor.session.writes:
                name = w.parsed_name()
                if name and name not in js_writes_by_name:
                    js_writes_by_name[name] = {
                        "frame_url": w.frame_url,
                        "raw_value": w.raw_value,
                        "stack": w.stack,
                        "ts": w.ts,
                    }

        # map url to request log entry for EasyPrivacy lookup
        request_by_url: dict[str, Any] = {}
        for r in request_log:
            url = r.get("url", "")
            if url and url not in request_by_url:
                request_by_url[url] = r

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
                expires_at = datetime.fromtimestamp(
                    expires, tz=timezone.utc
                ).isoformat()
                lifetime_days = (expires - now_ts) / 86400

            tracker_detection = None
            if tracker_list is not None:
                tracker_detection = tracker_list.is_tracker(cookie)
                if tracker_detection:
                    num_trackers += 1

            network_ctx = cookie_set_context.get((cookie_name, registered), {})
            set_by_url = network_ctx.get("set_by_request_url")

            ep_matched = False
            if set_by_url:
                req_entry = request_by_url.get(set_by_url)
                if req_entry:
                    ep_matched = bool(
                        (req_entry.get("easyprivacy") or {}).get("matched")
                    )

            set_by_js = js_writes_by_name.get(cookie_name)

            # Flat setter fields — HTTP and JS paths have different shapes.
            if set_by_url:
                setter_type = "http"
                setter_fields: dict[str, Any] = {
                    "setter_url": set_by_url,
                    "setter_request_type": network_ctx.get("set_by_request_type"),
                    "setter_third_party": network_ctx.get("is_third_party_set"),
                    "setter_ep_matched": ep_matched,
                }
                initiator = network_ctx.get("set_by_initiator") or ""
                if initiator:
                    setter_fields["setter_initiator"] = initiator
            elif set_by_js:
                setter_type = "javascript"
                setter_fields = {
                    "setter_frame_url": set_by_js.get("frame_url"),
                    "setter_raw_value": set_by_js.get("raw_value"),
                }
            else:
                setter_type = "unknown"
                setter_fields = {}

            # Flat tracker fields (null when not a tracker).
            tracker_lists_out: list[str] | None = None
            tracker_provider_out: str | None = None
            if tracker_detection:
                td = tracker_detection.to_dict()
                lists = td.get("lists") or []
                if lists:
                    tracker_lists_out = list(lists)
                    tracker_provider_out = td.get("matched_domain") or None

            cookies_out.append(
                {
                    "name": cookie_name,
                    "domain": cookie_domain,
                    "value": cookie.get("value", EMPTY_COOKIE),
                    "cookie_type": cookie_type,
                    "secure": cookie.get("secure"),
                    "http_only": cookie.get("httpOnly"),
                    "same_site": cookie.get("sameSite"),
                    "expires_at": expires_at,
                    "lifetime_days": lifetime_days,
                    "setter_type": setter_type,
                    **setter_fields,
                    "tracker_lists": tracker_lists_out,
                    "tracker_provider": tracker_provider_out,
                }
            )

        total_requests = len(request_log)
        ep_matched_count = sum(
            1 for r in request_log if (r.get("easyprivacy") or {}).get("matched")
        )

        js_reads = (
            len(cookie_read_interceptor.session.reads)
            if cookie_read_interceptor is not None
            else 0
        )
        js_writes = (
            len(cookie_read_interceptor.session.writes)
            if cookie_read_interceptor is not None
            else 0
        )

        summary: Dict[str, Any] = {
            "cookies": {
                "total": len(cookies_out),
                "session": num_session,
                "persistent": num_persistent,
            },
            "requests": {
                "total": total_requests,
                "easyprivacy": ep_matched_count,
                "easyprivacy_pct": (
                    round(ep_matched_count / total_requests * 100, 1)
                    if total_requests
                    else 0.0
                ),
            },
            "js": {
                "reads": js_reads,
                "writes": js_writes,
            },
            "sensitivity": sensitivity_result,
        }

        if tracker_list is not None:
            summary["cookies"]["trackers"] = num_trackers
            summary["cookies"]["tracker_pct"] = (
                round(num_trackers / len(cookies_out) * 100, 1) if cookies_out else 0.0
            )

        # Pruned request log:
        #   - drop cookies_sent (always empty in practice)
        #   - drop status (not used in any analysis)
        #   - omit document_url when it equals target_url (redundant for ~all requests)
        #   - omit initiator when empty string (sparse)
        #   - omit redirect_chain when empty (only 2% of requests have redirects)
        target_url = output.target_url
        requests_out = []
        for r in request_log:
            req: dict[str, Any] = {
                "url": r.get("url", ""),
                "type": r.get("type", ""),
                "easyprivacy": r.get("easyprivacy", {"matched": False}),
            }
            doc_url = r.get("document_url", "")
            if doc_url and doc_url != target_url:
                req["document_url"] = doc_url
            initiator = r.get("initiator", "")
            if initiator:
                req["initiator"] = initiator
            redirect_chain = r.get("redirect_chain") or []
            if redirect_chain:
                req["redirect_chain"] = redirect_chain
            requests_out.append(req)

        output_data: Dict[str, Any] = {
            "target_url": target_url,
            "collected_at": now.isoformat(),
            "crawl_context": {
                "country": output.country,
                "browser": output.browser,
                "rank": output.rank,
                "category": output.category,
            },
            "summary": summary,
            "cookies": cookies_out,
        }

        if requests_out:
            output_data["requests"] = requests_out

        if cookie_read_interceptor is not None:
            output_data["js_activity"] = cookie_read_interceptor.session.to_dict()

        if output.dir:
            os.makedirs(output.dir, exist_ok=True)
            output_path = os.path.join(output.dir, output.name)
        else:
            output_path = output.name

        tmp_path = output_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=None)
        os.replace(tmp_path, output_path)
