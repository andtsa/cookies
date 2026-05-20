import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .trackers import TrackerList


class CookiesUtils:
    @staticmethod
    def process_and_save(
        cookies: List[Dict[str, Any]],
        output_dir: str,
        output_name: str,
        params: Dict[str, Any],
        tracker_list: Optional[TrackerList] = None,
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

            if is_session or expires == -1:
                num_session += 1
                cookie_type = "session"
                expiration_datetime = None
                lifetime_seconds = None
                lifetime_days = None

            else:
                num_persistent += 1
                cookie_type = "persistent"

                expiration_datetime = datetime.fromtimestamp(
                    expires, tz=timezone.utc
                ).isoformat()

                lifetime_seconds = expires - now_ts
                lifetime_days = lifetime_seconds / 86400

                if lifetime_days >= 0:
                    lifetime_values.append(lifetime_days)

            tracker_detection = None
            if tracker_list is not None:
                tracker_detection = tracker_list.is_tracker(cookie)
                if tracker_detection:
                    num_trackers += 1

            single_cookie_metadata = {
                "name": cookie_name,
                "domain": cookie_domain,
                "session": is_session,
                "cookie_type": cookie_type,
                "secure": cookie.get("secure"),
                "httpOnly": cookie.get("httpOnly"),
                "sameSite": cookie.get("sameSite"),
                "expires_unix": expires,
                "expiration_datetime": expiration_datetime,
                "lifetime_seconds": lifetime_seconds,
                "lifetime_days": lifetime_days,
            }

            if tracker_detection is not None:
                single_cookie_metadata["is_tracker"] = tracker_detection.to_dict()
            else:
                single_cookie_metadata["is_tracker"] = False

            cookies_metadata.append(single_cookie_metadata)

        avg_lifetime_days = (
            sum(lifetime_values) / len(lifetime_values) if lifetime_values else None
        )
        max_lifetime_days = max(lifetime_values) if lifetime_values else None
        min_lifetime_days = min(lifetime_values) if lifetime_values else None

        site_metadata = {
            "collection_timestamp": now.isoformat(),
            "wait_time_seconds": params.get("wait_time_seconds"),
            "total_cookies": len(cookies_metadata),
            "num_session": num_session,
            "num_persistent": num_persistent,
            "avg_lifetime_days": avg_lifetime_days,
            "min_lifetime_days": min_lifetime_days,
            "max_lifetime_days": max_lifetime_days,
        }

        if tracker_list is not None:
            site_metadata["num_trackers"] = num_trackers
            site_metadata["pct_trackers"] = (
                round(num_trackers / len(cookies_metadata) * 100, 1)
                if cookies_metadata
                else 0.0
            )

        output_data = {
            "target_url": params.get("target_url"),
            "site_metadata": site_metadata,
            "cookies": cookies_metadata,
        }

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, output_name)
        else:
            output_path = output_name

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4)
