import argparse
import json
import os
import socket
import threading
import time
from datetime import datetime, timezone, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


APP_NAME = "codex-monitor"
VERSION = "2.0"
DISCOVERY_MESSAGE = b"CODEX_MONITOR_DISCOVER_V1"

# --- Codex JSONL event → state mapping (from clawd-on-desk/agents/codex.js) ---

EVENT_STATE_MAP = {
    "event_msg:task_started": "thinking",
    "event_msg:user_message": "thinking",
    "event_msg:agent_message": "working",
    "event_msg:mcp_tool_call_end": "working",
    "event_msg:patch_apply_end": "working",
    "event_msg:web_search_end": "working",
    "response_item:function_call": "working",
    "response_item:function_call_output": "working",
    "response_item:custom_tool_call": "working",
    "response_item:custom_tool_call_output": "working",
    "response_item:web_search_call": "working",
    "response_item:tool_search_call": "working",
    "response_item:tool_search_output": "working",
    "response.created": "thinking",
    "response.output_item.added": "working",
    "response.function_call_arguments.delta": "working",
    "response.completed": "attention",
    "event_msg:task_complete": "attention",
    "event_msg:context_compacted": "sweeping",
    "compacted": "sweeping",
    "event_msg:turn_aborted": "idle",
    "error": "error",
}

# State priority (higher index = higher priority)
STATE_PRIORITY = [
    "sleeping",
    "idle",
    "thinking",
    "working",
    "juggling",
    "attention",
    "sweeping",
    "notification",
    "error",
]

# Minimum display time for one-shot states (seconds)
MIN_DISPLAY_TIME = {
    "attention": 5,
    "error": 8,
    "sweeping": 3,
    "notification": 5,
}

# State → animation mapping
STATE_ANIMATION_MAP = {
    "thinking": "thinking",
    "working": "typing",
    "juggling": "juggling",
    "attention": "happy",
    "sweeping": "sweeping",
    "notification": "notification",
    "error": "error",
    "idle": "idle",
    "sleeping": "sleeping",
}

# State → Chinese label
STATE_LABEL_MAP = {
    "thinking": "思考中",
    "working": "写代码中",
    "juggling": "多任务进行中",
    "attention": "刚完成",
    "sweeping": "压缩上下文中",
    "notification": "有通知",
    "error": "出错了",
    "idle": "空闲",
    "sleeping": "睡眠",
}

# Decay thresholds
WORKING_DECAY_SECONDS = 30  # working/thinking → idle after 30s no event
IDLE_DECAY_SECONDS = 300  # idle → sleeping after 5 min no event


class CodexSessionTracker:
    """Tracks a single Codex rollout JSONL file."""

    def __init__(self, path: Path, debug: bool = False):
        self.path = path
        self.debug = debug
        self.offset = 0
        self.partial_line = ""
        self.session_id = path.stem  # rollout-XXXX
        # Use file mtime so old files aren't treated as just-active
        try:
            self.last_event_at = path.stat().st_mtime
        except OSError:
            self.last_event_at = 0.0
        self.last_state = "idle"
        self.last_event_text = ""
        self.cwd = ""
        self.quotas = []
        self.quota_updated_at = ""

    def read_new_events(self):
        """Read new lines from the JSONL file incrementally."""
        events = []
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                # File was truncated/rotated
                self.offset = 0
                self.partial_line = ""

            if size <= self.offset:
                return events

            with self.path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self.offset)
                raw = f.read()
                self.offset = f.tell()
        except (OSError, IOError):
            return events

        raw = self.partial_line + raw
        lines = raw.split("\n")
        # Last element might be incomplete
        self.partial_line = lines[-1]
        lines = lines[:-1]

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                events.append(obj)
            except (json.JSONDecodeError, ValueError):
                continue

        return events

    def process_events(self, events):
        """Process events and update state."""
        for event in events:
            keys = self._extract_event_keys(event)
            mapped = None
            mapped_key = ""
            for key in keys:
                mapped = EVENT_STATE_MAP.get(key)
                if mapped:
                    mapped_key = key
                    break

            if self.debug:
                print(
                    f"[JSONL] file={self.session_id} "
                    f"keys={','.join(keys) or '<none>'} mapped={mapped or '-'}"
                )

            if mapped:
                self.last_state = mapped
                # Use event timestamp if available, otherwise file-read time
                event_ts = self._extract_timestamp(event)
                self.last_event_at = event_ts if event_ts else time.time()
                self.last_event_text = mapped_key

            payload = event.get("payload", {})

            # Try to extract cwd
            if isinstance(payload, dict) and "cwd" in payload:
                self.cwd = payload["cwd"]
            self._extract_quota(event)

    def _extract_event_keys(self, event):
        """Extract possible mapping keys from known Codex JSONL event shapes."""
        keys = []
        event_type = event.get("type", "")
        payload = event.get("payload", {})
        payload_type = payload.get("type", "") if isinstance(payload, dict) else ""

        if event_type and payload_type:
            keys.append(f"{event_type}:{payload_type}")
        if event_type:
            keys.append(event_type)

        event_name = event.get("event", "")
        if event_name:
            keys.append(event_name)

        if isinstance(payload, str) and event_type:
            keys.append(f"{event_type}:{payload}")

        seen = set()
        unique = []
        for key in keys:
            if key and key not in seen:
                seen.add(key)
                unique.append(key)
        return unique

    def _extract_event_key(self, event):
        """Backward-compatible alias used by ad-hoc debug scripts."""
        return self._extract_event_keys(event)

    def _extract_quota(self, event):
        payload = event.get("payload", {})
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            return

        rate_limits = payload.get("rate_limits")
        if not isinstance(rate_limits, dict):
            return

        quotas = []
        primary = rate_limits.get("primary")
        if isinstance(primary, dict):
            quotas.append(self._quota_from_rate_limit(
                "five_hour",
                "5 小时限额",
                primary,
            ))

        secondary = rate_limits.get("secondary")
        if isinstance(secondary, dict):
            quotas.append(self._quota_from_rate_limit(
                "weekly",
                "周限额",
                secondary,
            ))

        if quotas:
            updated_at = self._extract_timestamp(event) or time.time()
            updated_iso = datetime.fromtimestamp(
                updated_at, tz=timezone.utc
            ).isoformat()
            for quota in quotas:
                quota["quotaSource"] = "live-jsonl"
                quota["quotaUpdatedAt"] = updated_iso
                quota["planType"] = rate_limits.get("plan_type") or ""
                quota["limitId"] = rate_limits.get("limit_id") or ""
                quota["limitName"] = rate_limits.get("limit_name") or ""
            self.quotas = quotas
            self.quota_updated_at = updated_iso

    @staticmethod
    def _quota_from_rate_limit(quota_id, label, data):
        used = data.get("used_percent", 0)
        try:
            used = float(used)
        except (TypeError, ValueError):
            used = 0.0
        used = max(0.0, min(100.0, used))

        resets_at = data.get("resets_at", "")
        reset_at = ""
        if isinstance(resets_at, (int, float)) and resets_at > 0:
            reset_at = datetime.fromtimestamp(
                float(resets_at), tz=timezone.utc
            ).isoformat()

        window_minutes = data.get("window_minutes", 0)
        return {
            "id": quota_id,
            "label": label,
            "used": round(used, 2),
            "limit": 100,
            "unit": "%",
            "resetAt": reset_at,
            "windowMinutes": window_minutes,
        }

    @staticmethod
    def _extract_timestamp(event):
        """Try to extract a Unix timestamp from a JSONL event."""
        # Codex JSONL events may have a top-level "timestamp" or nested timestamp
        for field in ("timestamp", "ts", "time"):
            parsed = CodexSessionTracker._parse_timestamp_value(event.get(field))
            if parsed:
                return parsed
        # Check payload.timestamp
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            for field in ("timestamp", "ts", "time"):
                parsed = CodexSessionTracker._parse_timestamp_value(
                    payload.get(field)
                )
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _parse_timestamp_value(value):
        if isinstance(value, (int, float)) and value > 1_000_000_000:
            return float(value)
        if isinstance(value, str):
            raw = value.strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except (ValueError, TypeError):
                return None
        return None

    def get_effective_state(self):
        """Get current state with decay applied."""
        elapsed = time.time() - self.last_event_at

        # Sleeping takes precedence: any state with no events for 5 min
        if elapsed > IDLE_DECAY_SECONDS:
            return "sleeping"

        # Working/thinking decays to idle after 30s
        if self.last_state in ("working", "thinking"):
            if elapsed > WORKING_DECAY_SECONDS:
                return "idle"

        return self.last_state

    def is_stale(self):
        """Whether this session is too old to track."""
        return (time.time() - self.last_event_at) > IDLE_DECAY_SECONDS


class CodexSessionMonitor:
    """Monitors all active Codex sessions by scanning JSONL rollout files."""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.sessions_dir = Path.home() / ".codex" / "sessions"
        self.trackers: dict[str, CodexSessionTracker] = {}
        self.lock = threading.Lock()
        self._running = False
        self._thread = None
        # Aggregate state
        self.current_state = "idle"
        self.current_animation = "idle"
        self.current_label = "空闲"
        self.current_detail = ""
        self.active_sessions = 0
        self.last_update = time.time()
        self.events_log: list[dict] = []
        self.latest_quotas = []
        self.latest_quota_updated_at = ""
        # Min display state tracking
        self._forced_state = None
        self._forced_until = 0.0

    def start(self):
        """Start background monitoring thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _monitor_loop(self):
        while self._running:
            self._scan_and_update()
            time.sleep(1.0)  # Poll every 1 second

    def _get_scan_dirs(self):
        """Get today and yesterday's session directories."""
        dirs = []
        now = datetime.now()
        for delta in (0, 1):
            d = now - timedelta(days=delta)
            p = self.sessions_dir / d.strftime("%Y") / d.strftime("%m") / d.strftime("%d")
            if p.is_dir():
                dirs.append(p)
        return dirs

    def _scan_and_update(self):
        """Scan for rollout files and process new events."""
        if not self.sessions_dir.is_dir():
            return

        scan_dirs = self._get_scan_dirs()
        active_files = set()

        for d in scan_dirs:
            try:
                for f in d.glob("rollout-*.jsonl"):
                    active_files.add(str(f))
                    key = str(f)
                    if key not in self.trackers:
                        self.trackers[key] = CodexSessionTracker(f, debug=self.debug)
            except OSError:
                continue

        # Process events for all tracked files
        with self.lock:
            for key, tracker in list(self.trackers.items()):
                events = tracker.read_new_events()
                if events:
                    tracker.process_events(events)
                    if (
                        tracker.quotas
                        and tracker.quota_updated_at >= self.latest_quota_updated_at
                    ):
                        self.latest_quotas = [dict(q) for q in tracker.quotas]
                        self.latest_quota_updated_at = tracker.quota_updated_at

            # Remove stale trackers (sleeping sessions aren't useful to keep)
            for key in list(self.trackers.keys()):
                if self.trackers[key].is_stale():
                    del self.trackers[key]

            # Compute aggregate state
            self._compute_aggregate()

    def _compute_aggregate(self):
        """Compute the aggregate state from all active sessions."""
        active_states = []
        active_count = 0
        latest_event_text = ""
        latest_event_time = 0.0

        for tracker in self.trackers.values():
            state = tracker.get_effective_state()
            if state not in ("sleeping", "idle"):
                active_count += 1
                active_states.append(state)
            elif state == "idle":
                active_states.append(state)
            if tracker.last_event_at > latest_event_time:
                latest_event_time = tracker.last_event_at
                latest_event_text = tracker.last_event_text

        self._last_event_time = latest_event_time

        # Check forced (min display) state
        now = time.time()
        if self._forced_state and now < self._forced_until:
            # Honor min display time unless new state has higher priority
            best_new = self._highest_priority(active_states) if active_states else "idle"
            if self._priority_of(best_new) <= self._priority_of(self._forced_state):
                chosen = self._forced_state
            else:
                chosen = best_new
                self._forced_state = None
        else:
            self._forced_state = None
            if not active_states:
                chosen = "sleeping" if not self.trackers else "idle"
            elif active_count >= 2 and self._count_working(active_states) >= 2:
                chosen = "juggling"
            else:
                chosen = self._highest_priority(active_states)

        # Set min display for one-shot states
        if chosen != self.current_state and chosen in MIN_DISPLAY_TIME:
            self._forced_state = chosen
            self._forced_until = now + MIN_DISPLAY_TIME[chosen]

        self.current_state = chosen
        self.current_animation = STATE_ANIMATION_MAP.get(chosen, "idle")
        self.current_label = STATE_LABEL_MAP.get(chosen, "空闲")
        self.current_detail = f"最近事件：{latest_event_text}" if latest_event_text else ""
        self.active_sessions = active_count
        self.last_update = latest_event_time if latest_event_time > 0 else now

        # Keep event log (last 10)
        if latest_event_text and (
            not self.events_log
            or self.events_log[0].get("text") != STATE_LABEL_MAP.get(chosen, chosen)
        ):
            self.events_log.insert(0, {
                "time": datetime.now(timezone.utc).isoformat(),
                "text": STATE_LABEL_MAP.get(chosen, chosen),
            })
            self.events_log = self.events_log[:10]

    def _highest_priority(self, states):
        best = "idle"
        best_p = -1
        for s in states:
            p = self._priority_of(s)
            if p > best_p:
                best_p = p
                best = s
        return best

    def _priority_of(self, state):
        try:
            return STATE_PRIORITY.index(state)
        except ValueError:
            return -1

    def _count_working(self, states):
        return sum(1 for s in states if s in ("working", "thinking"))

    def get_status(self):
        """Get the current aggregated status dict."""
        with self.lock:
            # freshness reflects time since last real event, not last scan
            last_ev = getattr(self, '_last_event_time', 0.0)
            if last_ev > 0:
                elapsed = time.time() - last_ev
                updated_at = datetime.fromtimestamp(
                    last_ev, tz=timezone.utc
                ).isoformat()
            else:
                elapsed = 0.0
                updated_at = datetime.now(timezone.utc).isoformat()

            if elapsed < 5:
                freshness = "刚刚"
            elif elapsed < 60:
                freshness = f"{int(elapsed)}秒前"
            elif elapsed < 3600:
                freshness = f"{int(elapsed // 60)}分钟前"
            else:
                freshness = f"{int(elapsed // 3600)}小时前"

            return {
                "status": self.current_state,
                "statusLabel": self.current_label,
                "headline": f"Codex {self.current_label}",
                "detail": self.current_detail,
                "animation": self.current_animation,
                "updatedAt": updated_at,
                "freshness": freshness,
                "activeSessions": self.active_sessions,
                "events": self.events_log[:5],
                "quotas": self._get_latest_quotas(),
                "quotaSource": self._get_quota_source(),
            }

    def _get_latest_quotas(self):
        latest_time = ""
        latest_quotas = []
        for tracker in self.trackers.values():
            if tracker.quotas and tracker.quota_updated_at >= latest_time:
                latest_time = tracker.quota_updated_at
                latest_quotas = tracker.quotas
        if not latest_quotas and self.latest_quotas:
            latest_quotas = self.latest_quotas
        return [dict(q) for q in latest_quotas]

    def _get_quota_source(self):
        if not self._get_latest_quotas():
            return "unknown"
        if self.active_sessions > 0:
            return "live-jsonl"
        return "stale-jsonl"


class MonitorState:
    def __init__(self, root: Path, codex_monitor: CodexSessionMonitor):
        self.root = root
        self.status_path = root / "codex-status.json"
        self.codex_monitor = codex_monitor

    def read(self):
        # Get real-time status from CodexSessionMonitor
        live_status = self.codex_monitor.get_status()
        has_live = self.codex_monitor.active_sessions > 0 or bool(
            self.codex_monitor.trackers
        )

        # Read manual/fallback JSON
        manual_data = self._read_manual_json()

        if has_live:
            # Merge: use live state but keep manual quotas if no live quota source
            result = {**live_status}
            if live_status.get("quotas"):
                result["quotaSource"] = live_status.get("quotaSource", "live-jsonl")
            else:
                result["quotas"] = self._annotate_quotas(
                    manual_data.get("quotas", []), "manual"
                )
                result["quotaSource"] = "manual"
            # Keep legacy fields for backward compat
            result["title"] = live_status["statusLabel"]
            result["task"] = live_status["headline"]
            result["log"] = [
                {"time": e["time"], "text": e["text"]}
                for e in live_status.get("events", [])
            ]
        else:
            # Fallback to manual JSON entirely
            result = manual_data.copy()
            if live_status.get("quotas"):
                result["quotas"] = live_status["quotas"]
                result["quotaSource"] = live_status.get("quotaSource", "stale-jsonl")
            else:
                result["quotas"] = self._annotate_quotas(
                    manual_data.get("quotas", []), "manual"
                )
                result["quotaSource"] = "manual"
            # Add new fields with fallback values
            status = manual_data.get("status", "idle")
            animation = self._status_to_animation(status)
            label = STATE_LABEL_MAP.get(status, status)
            result["statusLabel"] = label
            result["headline"] = manual_data.get("task", f"Codex {label}")
            result["detail"] = ""
            result["animation"] = animation
            result["updatedAt"] = manual_data.get(
                "updatedAt", datetime.now(timezone.utc).isoformat()
            )
            result["freshness"] = self._compute_freshness(
                manual_data.get("updatedAt")
            )
            result["activeSessions"] = 0
            result["events"] = manual_data.get("log", [])[:5]
            # Keep legacy fields
            result.setdefault("title", label)
            result.setdefault("task", "")
            result.setdefault("log", [])

        return result

    def _read_manual_json(self):
        if self.status_path.exists():
            try:
                with self.status_path.open("r", encoding="utf-8-sig") as handle:
                    return json.load(handle)
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "status": "idle",
            "title": "空闲",
            "task": "",
            "quotas": [
                {
                    "id": "five_hour",
                    "label": "5 小时限额",
                    "used": 0,
                    "limit": 100,
                    "unit": "%",
                    "resetAt": "",
                },
                {
                    "id": "weekly",
                    "label": "周限额",
                    "used": 0,
                    "limit": 100,
                    "unit": "%",
                    "resetAt": "",
                },
            ],
        }

    def _annotate_quotas(self, quotas, source):
        """Add quotaSource and quotaUpdatedAt to each quota entry."""
        now_iso = datetime.now(timezone.utc).isoformat()
        annotated = []
        for q in quotas:
            entry = dict(q)
            if "quotaSource" not in entry:
                entry["quotaSource"] = source
            if "quotaUpdatedAt" not in entry:
                entry["quotaUpdatedAt"] = now_iso
            annotated.append(entry)
        return annotated

    def _status_to_animation(self, status):
        mapping = {
            "thinking": "thinking",
            "working": "typing",
            "testing": "building",
            "blocked": "error",
            "done": "happy",
            "idle": "idle",
        }
        return mapping.get(status, "idle")

    def _compute_freshness(self, updated_at_str):
        if not updated_at_str:
            return "未知"
        try:
            updated = datetime.fromisoformat(updated_at_str)
            now = datetime.now(timezone.utc)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            elapsed = (now - updated).total_seconds()
            if elapsed < 5:
                return "刚刚"
            elif elapsed < 60:
                return f"{int(elapsed)}秒前"
            elif elapsed < 3600:
                return f"{int(elapsed // 60)}分钟前"
            else:
                return f"{int(elapsed // 3600)}小时前"
        except (ValueError, TypeError):
            return "未知"


def local_ipv4_addresses():
    addresses = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in addresses and not ip.startswith("127."):
                addresses.append(ip)
    except OSError:
        pass

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        if ip not in addresses and not ip.startswith("127."):
            addresses.append(ip)
    except OSError:
        pass
    finally:
        probe.close()
    return addresses


def make_handler(root: Path, state: MonitorState, http_port: int):
    class Handler(SimpleHTTPRequestHandler):
        server_version = "CodexMonitor/2.0"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/api/ping":
                self.send_json({
                    "app": APP_NAME,
                    "version": VERSION,
                    "httpPort": http_port,
                    "statusPath": "/api/status",
                })
                return
            if path == "/api/status":
                self.send_json(state.read())
                return
            if path == "/":
                self.path = "/codex-monitor.html"
            return super().do_GET()

        def send_json(self, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            print("%s - %s" % (self.client_address[0], format % args))

    return Handler


def discovery_loop(http_port: int, discovery_port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", discovery_port))
    print(f"Discovery listening on UDP {discovery_port}")
    while True:
        try:
            data, address = sock.recvfrom(2048)
            if data.strip() != DISCOVERY_MESSAGE:
                continue
            payload = json.dumps({
                "app": APP_NAME,
                "version": VERSION,
                "httpPort": http_port,
                "statusPath": "/api/status",
            }).encode("utf-8")
            sock.sendto(payload, address)
        except OSError as exc:
            print(f"Discovery error: {exc}")


def main():
    parser = argparse.ArgumentParser(description="Codex monitor desktop server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--discovery-port", type=int, default=45777)
    parser.add_argument("--root", default=os.path.dirname(__file__))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    # Start Codex session monitor
    codex_monitor = CodexSessionMonitor(debug=args.debug)
    codex_monitor.start()
    print("CodexSessionMonitor started — watching ~/.codex/sessions/")

    state = MonitorState(root, codex_monitor)
    handler = make_handler(root, state, args.port)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    thread = threading.Thread(
        target=discovery_loop,
        args=(args.port, args.discovery_port),
        daemon=True,
    )
    thread.start()

    print("Codex Monitor server is running (v2.0)")
    print(f"Local: http://127.0.0.1:{args.port}/")
    for ip in local_ipv4_addresses():
        print(f"LAN:   http://{ip}:{args.port}/")
    print("Android app will discover this server automatically on the same Wi-Fi.")
    server.serve_forever()


if __name__ == "__main__":
    main()
