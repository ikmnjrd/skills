"""Codex monitor bridge, launcher, and optional command shim.

This is a standard-library Python port of upstream agmsg's beta Codex monitor
implementation. Interactive Codex sessions are connected to a shared
``codex app-server`` Unix socket. A bridge watches agmsg's unread cursor via
the app-server ``process/spawn`` API and turns each wakeup into a serialized
``turn/start`` on the live Codex thread.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import secrets
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import identity, locking, storage
from . import platform as plat
from .envelope import AgmsgError

MONITOR_DOC_URL = (
    "https://github.com/ikmnjrd/agmsg/blob/main/docs/codex-monitor-beta.md"
)
SHIM_MARKER = "Optional Codex entrypoint shim for agmsg monitor mode."


def _project_hash(project: str) -> str:
    return hashlib.sha1(project.encode("utf-8")).hexdigest()


def socket_path(project: str) -> Path:
    return plat.run_dir() / f"codex-app-server.{_project_hash(project)}.sock"


def request_path(project: str) -> Path:
    return plat.run_dir() / f"codex-bridge-request.{_project_hash(project)}.json"


def _identity_key(team: str, name: str) -> str:
    return hashlib.sha256(f"{team}\0{name}".encode("utf-8")).hexdigest()[:24]


def bridge_path(team: str, name: str, suffix: str) -> Path:
    return plat.run_dir() / f"codex-bridge.{_identity_key(team, name)}.{suffix}"


def _pid_alive(pid: int) -> bool:
    return locking._pid_alive(pid)


def _read_pid(path: Path) -> int:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
        return value if value > 0 else 0
    except (OSError, ValueError):
        return 0


def resolve_thread_id(project: str) -> str:
    """Resolve the current Codex thread from env or the newest matching rollout."""
    thread_id = os.environ.get("CODEX_THREAD_ID", "")
    if thread_id:
        return thread_id
    home = os.environ.get("HOME")
    if not home:
        return ""
    sessions = Path(home) / ".codex" / "sessions"
    if not sessions.is_dir():
        return ""
    for attempt in range(3):
        try:
            files = sorted(
                sessions.rglob("rollout-*.jsonl"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:20]
        except OSError:
            files = []
        for path in files:
            try:
                with path.open(encoding="utf-8") as stream:
                    first = stream.readline()
                item = json.loads(first)
            except (OSError, ValueError):
                continue
            if item.get("type") != "session_meta":
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict) or payload.get("cwd") != project:
                continue
            value = payload.get("id")
            if isinstance(value, str) and value:
                return value
        if attempt < 2:
            time.sleep(1)
    return ""


def publish_session_request(project: str) -> bool:
    """Publish the Codex SessionStart rendezvous consumed by the launcher."""
    pairs = identity.identities(project, "codex")
    if len(pairs) != 1:
        return False
    thread_id = resolve_thread_id(project)
    app_server = os.environ.get("AGMSG_CODEX_BRIDGE_APP_SERVER", "")
    if not thread_id or not app_server:
        return False
    team, name = pairs[0]
    payload = {
        "type": "codex",
        "project": project,
        "team": team,
        "name": name,
        "thread": thread_id,
        "app_server": app_server,
        "created_at": time.time(),
    }
    path = request_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return True


def watch_once(
    project: str,
    agent_type: str,
    *,
    team: str | None = None,
    name: str | None = None,
    timeout: int = 300,
    interval: int = 2,
) -> int:
    """Wait until a subscription has unread rows.

    Exit 0 means pending, exit 2 means timeout, and exit 1 is configuration
    failure. Messages are deliberately not marked read.
    """
    pairs = identity.identities(project, agent_type)
    if team:
        pairs = [(t, a) for t, a in pairs if t == team]
    if name:
        pairs = [(t, a) for t, a in pairs if a == name]
    if not pairs:
        sys.stderr.write(
            "watch-once: no available subscription for "
            f"project={project} type={agent_type} "
            f"name={name or '*'} team={team or '*'}\n"
        )
        return 1
    deadline = time.monotonic() + timeout
    while True:
        count, max_id = storage.unread_status(pairs)
        if count:
            sys.stdout.write(f"status=pending count={count} max_id={max_id}\n")
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            sys.stdout.write("status=timeout\n")
            return 2
        time.sleep(min(max(interval, 1), remaining))


class _RpcClient:
    def __init__(self) -> None:
        self._next_id = 1
        self._pending: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()
        self.events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue()
        self.closed = False

    def start(self) -> None:
        raise NotImplementedError

    def send_json(self, value: dict[str, Any]) -> None:
        raise NotImplementedError

    def request(
        self, method: str, params: dict[str, Any], timeout: float = 30
    ) -> Any:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            waiter: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter
        self.send_json(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        try:
            result = waiter.get(timeout=timeout)
        except queue.Empty as exc:
            self._pending.pop(request_id, None)
            raise RuntimeError(f"app-server request timed out: {method}") from exc
        if isinstance(result, Exception):
            raise result
        return result

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.send_json(
            {"jsonrpc": "2.0", "method": method, "params": params or {}}
        )

    def _message(self, message: dict[str, Any]) -> None:
        if "id" in message:
            waiter = self._pending.pop(message["id"], None)
            if waiter:
                if message.get("error"):
                    error = message["error"]
                    text = (
                        error.get("message", json.dumps(error))
                        if isinstance(error, dict)
                        else str(error)
                    )
                    waiter.put(RuntimeError(text))
                else:
                    waiter.put(message.get("result"))
            return
        method = message.get("method")
        if isinstance(method, str):
            params = message.get("params")
            self.events.put((method, params if isinstance(params, dict) else {}))

    def _close(self, error: Exception | None = None) -> None:
        if self.closed:
            return
        self.closed = True
        failure = error or RuntimeError("app-server connection closed")
        for waiter in list(self._pending.values()):
            waiter.put(failure)
        self._pending.clear()
        self.events.put(("_closed", {"error": str(failure)}))

    def stop(self) -> None:
        raise NotImplementedError


class StdioRpcClient(_RpcClient):
    def __init__(self, command: list[str], cwd: str) -> None:
        super().__init__()
        self.command = command
        self.cwd = cwd
        self.child: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()

    def start(self) -> None:
        self.child = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.child and self.child.stdout
        try:
            for line in self.child.stdout:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    sys.stderr.write(
                        f"codex-bridge: ignoring non-json app-server line: {line}"
                    )
                    continue
                if isinstance(value, dict):
                    self._message(value)
        finally:
            self._close()

    def send_json(self, value: dict[str, Any]) -> None:
        if not self.child or not self.child.stdin:
            raise RuntimeError("app-server is not running")
        data = json.dumps(value, separators=(",", ":")) + "\n"
        with self._write_lock:
            self.child.stdin.write(data)
            self.child.stdin.flush()

    def stop(self) -> None:
        if self.child:
            if self.child.stdin and not self.child.stdin.closed:
                try:
                    self.child.stdin.close()
                except OSError:
                    pass
            if self.child.poll() is None:
                try:
                    self.child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.child.terminate()
                    try:
                        self.child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.child.kill()
                        self.child.wait(timeout=1)
            if self.child.stdout and not self.child.stdout.closed:
                self.child.stdout.close()
        self._close()


class UnixWebSocketRpcClient(_RpcClient):
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.sock: socket.socket | None = None
        self._write_lock = threading.Lock()

    def start(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.path)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        header = self._recv_until(sock, b"\r\n\r\n", 65536)
        first, *lines = header.decode("latin1").split("\r\n")
        if not first.startswith("HTTP/1.1 101"):
            sock.close()
            raise RuntimeError(f"app-server websocket upgrade failed: {first}")
        headers = {}
        for line in lines:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            sock.close()
            raise RuntimeError("app-server websocket returned an invalid accept key")
        self.sock = sock
        threading.Thread(target=self._read, daemon=True).start()

    @staticmethod
    def _recv_until(sock: socket.socket, marker: bytes, cap: int) -> bytes:
        data = bytearray()
        while marker not in data:
            # Read one byte at a time during the small HTTP handshake so a
            # WebSocket frame coalesced into the next packet is not discarded.
            chunk = sock.recv(1)
            if not chunk:
                raise RuntimeError("app-server socket closed during handshake")
            data.extend(chunk)
            if len(data) > cap:
                raise RuntimeError("app-server websocket handshake is too large")
        head, _sep, _rest = bytes(data).partition(marker)
        return head + marker

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise EOFError("app-server socket closed")
            data.extend(chunk)
        return bytes(data)

    def _read(self) -> None:
        assert self.sock
        try:
            while True:
                first, second = self._recv_exact(self.sock, 2)
                opcode = first & 0x0F
                length = second & 0x7F
                masked = bool(second & 0x80)
                if length == 126:
                    length = struct.unpack("!H", self._recv_exact(self.sock, 2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", self._recv_exact(self.sock, 8))[0]
                mask = self._recv_exact(self.sock, 4) if masked else b""
                payload = self._recv_exact(self.sock, length)
                if masked:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                if opcode == 0x1:
                    value = json.loads(payload.decode("utf-8"))
                    if isinstance(value, dict):
                        self._message(value)
                elif opcode == 0x8:
                    break
                elif opcode == 0x9:
                    self._send_frame(0xA, payload)
        except (OSError, EOFError, ValueError) as exc:
            self._close(exc)
        finally:
            self._close()

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        assert self.sock
        with self._write_lock:
            self.sock.sendall(header + mask + masked)

    def send_json(self, value: dict[str, Any]) -> None:
        self._send_frame(
            0x1, json.dumps(value, separators=(",", ":")).encode("utf-8")
        )

    def stop(self) -> None:
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.sock.close()
        self._close()


def _app_server_client(
    project: str, app_server: str | None
) -> _RpcClient:
    if app_server:
        if not app_server.startswith("unix://"):
            raise AgmsgError(
                "bad_app_server",
                "--app-server currently supports only unix://PATH",
                2,
            )
        path = app_server[len("unix://") :]
        if not path:
            raise AgmsgError("bad_app_server", "unix:// requires a socket path", 2)
        return UnixWebSocketRpcClient(str(Path(path).resolve()))
    override = os.environ.get("AGMSG_CODEX_APP_SERVER_CMD")
    command = (
        shlex.split(override)
        if override
        else [
            os.environ.get("AGMSG_REAL_CODEX", "codex"),
            "app-server",
            "--listen",
            "stdio://",
        ]
    )
    return StdioRpcClient(command, project)


class CodexBridge:
    def __init__(
        self,
        project: str,
        team: str,
        name: str,
        *,
        agent_type: str = "codex",
        thread_id: str | None = None,
        app_server: str | None = None,
        timeout: int = 300,
        interval: int = 2,
        max_wakes: int = 0,
        stale_wake_limit: int = 1,
        turn_timeout: int = 60,
        inline_inbox: bool = False,
    ) -> None:
        self.project = str(Path(project).resolve())
        self.team = team
        self.name = name
        self.agent_type = agent_type
        self.thread_id = thread_id
        self.timeout = timeout
        self.interval = interval
        self.max_wakes = max_wakes
        self.stale_wake_limit = stale_wake_limit
        self.turn_timeout = turn_timeout
        self.inline_inbox = inline_inbox
        self.client = _app_server_client(self.project, app_server)
        self.thread_idle = True
        self.turn_active = False
        self.turn_deadline: float | None = None
        self.pending_wake = False
        self.watch_handle: str | None = None
        self.wake_count = 0
        self.last_wake_max_id = 0
        self.stale_wake_count = 0
        self.stopping = False
        self.pidfile = bridge_path(team, name, "pid")
        self.metafile = bridge_path(team, name, "meta")

    def run(self) -> int:
        self.pidfile.parent.mkdir(parents=True, exist_ok=True)
        self._single_instance()
        self._write_meta()
        old_handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            old_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda *_a: self._request_stop())
        try:
            self.client.start()
            self.client.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "agmsg-codex-bridge",
                        "title": "agmsg Codex bridge",
                        "version": "python-port",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "requestAttestation": False,
                        "optOutNotificationMethods": [],
                    },
                },
            )
            self.client.notify("initialized")
            self._ensure_thread()
            self._arm_watch()
            while not self.stopping:
                timeout = None
                if self.turn_deadline is not None:
                    timeout = max(0.0, self.turn_deadline - time.monotonic())
                try:
                    method, params = self.client.events.get(timeout=timeout)
                except queue.Empty:
                    sys.stderr.write(
                        "codex-bridge: no turn completion within "
                        f"{self.turn_timeout}s; assuming the turn ended and resuming\n"
                    )
                    if self._turn_ended():
                        break
                    continue
                if method == "_closed":
                    break
                if method == "_stop":
                    break
                if self._handle_event(method, params):
                    break
            return 0
        finally:
            self._shutdown()
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)

    def _request_stop(self) -> None:
        self.stopping = True
        self.client.events.put(("_stop", {}))

    def _ensure_thread(self) -> None:
        if self.thread_id:
            response = self.client.request(
                "thread/resume",
                {
                    "threadId": self.thread_id,
                    "cwd": self.project,
                    "runtimeWorkspaceRoots": [self.project],
                    "excludeTurns": True,
                },
            )
            thread = response.get("thread", {}) if isinstance(response, dict) else {}
            if thread.get("id") != self.thread_id:
                raise RuntimeError("thread/resume did not return requested thread id")
            status = thread.get("status", {})
            active = isinstance(status, dict) and status.get("type") == "active"
            self.thread_idle = not active
            self.turn_active = active
            sys.stderr.write(f"codex-bridge: resumed thread {self.thread_id}\n")
            return
        response = self.client.request(
            "thread/start",
            {
                "cwd": self.project,
                "runtimeWorkspaceRoots": [self.project],
                "ephemeral": False,
            },
        )
        thread = response.get("thread", {}) if isinstance(response, dict) else {}
        self.thread_id = thread.get("id")
        if not self.thread_id:
            raise RuntimeError("thread/start did not return a thread id")
        sys.stderr.write(f"codex-bridge: started thread {self.thread_id}\n")

    def _arm_watch(self) -> None:
        if self.stopping or self.watch_handle:
            return
        handle = f"agmsg-watch-{time.time_ns()}"
        command = [
            plat.python_executable(),
            str(plat.agmsg_py()),
            "watch-once",
            self.project,
            self.agent_type,
            "--team",
            self.team,
            "--name",
            self.name,
            "--timeout",
            str(self.timeout),
            "--interval",
            str(self.interval),
        ]
        self.client.request(
            "process/spawn",
            {
                "command": command,
                "processHandle": handle,
                "cwd": self.project,
                "outputBytesCap": 8192,
                "timeoutMs": (self.timeout + self.interval + 10) * 1000,
            },
        )
        self.watch_handle = handle
        sys.stderr.write(f"codex-bridge: armed {self.team}/{self.name}\n")

    def _handle_event(self, method: str, params: dict[str, Any]) -> bool:
        if method == "process/exited":
            if params.get("processHandle") != self.watch_handle:
                return False
            self.watch_handle = None
            code = params.get("exitCode")
            if code == 0:
                max_id = _parse_max_id(str(params.get("stdout", "")))
                if self._stale_wake(max_id):
                    self.stopping = True
                    raise AgmsgError(
                        "stale_wakeup",
                        "unread inbox did not advance; stopped repeated wakeup loop",
                    )
                self.pending_wake = True
                self.wake_count += 1
                sys.stderr.write(
                    f"codex-bridge: wakeup {self.wake_count} for "
                    f"{self.team}/{self.name}\n"
                )
                self._try_start_turn()
            elif code == 2:
                self._arm_watch()
            else:
                detail = "\n".join(
                    str(params.get(k, "")) for k in ("stderr", "stdout")
                    if params.get(k)
                ).strip()
                sys.stderr.write(
                    f"codex-bridge: watch-once failed with exit {code}"
                    f"{': ' + detail if detail else ''}\n"
                )
                time.sleep(1)
                self._arm_watch()
        elif method == "thread/status/changed":
            if params.get("threadId") != self.thread_id:
                return False
            status = params.get("status", {})
            kind = status.get("type") if isinstance(status, dict) else None
            if kind == "active":
                self.turn_active = True
                self.thread_idle = False
            elif kind == "idle":
                return self._turn_ended()
        elif method in ("turn/completed", "turn/failed"):
            if params.get("threadId") not in (None, self.thread_id):
                return False
            return self._turn_ended()
        elif method == "item/agentMessage/delta":
            if params.get("threadId") == self.thread_id:
                sys.stderr.write(str(params.get("delta", "")))
        elif method == "error":
            sys.stderr.write(
                "codex-bridge: server error: "
                + json.dumps(params, ensure_ascii=False)
                + "\n"
            )
        return False

    def _turn_ended(self) -> bool:
        self.turn_deadline = None
        self.turn_active = False
        self.thread_idle = True
        if self.max_wakes and self.wake_count >= self.max_wakes:
            return True
        if self.pending_wake:
            self._try_start_turn()
        else:
            self._arm_watch()
        return False

    def _try_start_turn(self) -> None:
        if not self.pending_wake or self.turn_active or not self.thread_idle:
            return
        inbox = self._read_inbox() if self.inline_inbox else ""
        if self.inline_inbox and not inbox.strip():
            sys.stderr.write(
                "codex-bridge: pending wake had no inbox output; re-arming\n"
            )
            self.pending_wake = False
            self._arm_watch()
            return
        prompt = self._prompt(inbox)
        self.turn_active = True
        self.thread_idle = False
        try:
            self.client.request(
                "turn/start",
                {
                    "threadId": self.thread_id,
                    "input": [{"type": "text", "text": prompt, "text_elements": []}],
                    "cwd": self.project,
                    "runtimeWorkspaceRoots": [self.project],
                },
            )
        except Exception:
            self.turn_active = False
            self.thread_idle = True
            raise
        self.pending_wake = False
        if self.turn_timeout:
            self.turn_deadline = time.monotonic() + self.turn_timeout
        sys.stderr.write(
            f"codex-bridge: started turn on thread {self.thread_id}\n"
        )

    def _read_inbox(self) -> str:
        rows = storage.unread(self.team, self.name)
        if not rows:
            return ""
        lines = [f"{len(rows)} new message(s):", ""]
        for row in rows:
            body = row["body"].replace("\n", "\\n").replace("\t", "\\t")
            lines.append(
                f"  [{row['created_at']}] {row['from_agent']}: {body}"
            )
        storage.mark_read(self.team, self.name)
        return "\n".join(lines)

    def _prompt(self, inbox: str) -> str:
        send = (
            f"{plat.python_executable()} {plat.agmsg_py()} send "
            f"{shlex.quote(self.team)} {shlex.quote(self.name)} <to> <message>"
        )
        if self.inline_inbox:
            return (
                f"agmsg delivered the following unread messages for "
                f"{self.team}/{self.name}:\n\n{inbox.strip()}\n\n"
                "Continue the conversation in this Codex thread. If a reply "
                f"is needed, send it with:\n{send}"
            )
        inbox_cmd = (
            f"{plat.python_executable()} {plat.agmsg_py()} inbox "
            f"{shlex.quote(self.team)} {shlex.quote(self.name)}"
        )
        return (
            f"agmsg has unread messages for {self.team}/{self.name}.\n"
            f"Run: {inbox_cmd}\nRead the messages and continue the conversation. "
            f"If a reply is needed, send it with:\n{send}"
        )

    def _stale_wake(self, max_id: int) -> bool:
        if max_id <= 0 or max_id != self.last_wake_max_id:
            self.last_wake_max_id = max_id
            self.stale_wake_count = 0
            return False
        self.stale_wake_count += 1
        sys.stderr.write(
            f"codex-bridge: unread max_id is still {max_id}; inbox was not "
            "marked read after the prior wakeup\n"
        )
        if self.stale_wake_limit and self.stale_wake_count >= self.stale_wake_limit:
            sys.stderr.write(
                "codex-bridge: stopping to avoid a repeated wakeup loop\n"
            )
            return True
        return False

    def _single_instance(self) -> None:
        existing = _read_pid(self.pidfile)
        if existing and _pid_alive(existing):
            raise AgmsgError(
                "bridge_running",
                f"bridge already running for {self.team}/{self.name} "
                f"(pid {existing})",
            )
        for path in (self.pidfile, self.metafile):
            try:
                path.unlink()
            except OSError:
                pass

    def _write_meta(self) -> None:
        self.pidfile.write_text(f"{os.getpid()}\n", encoding="utf-8")
        self.metafile.write_text(
            f"pid={os.getpid()}\nproject={self.project}\n"
            f"team={self.team}\nname={self.name}\ntype={self.agent_type}\n",
            encoding="utf-8",
        )

    def _shutdown(self) -> None:
        self.stopping = True
        if self.watch_handle and not self.client.closed:
            try:
                self.client.request(
                    "process/kill", {"processHandle": self.watch_handle}, timeout=2
                )
            except Exception:
                pass
        self.client.stop()
        if _read_pid(self.pidfile) == os.getpid():
            for path in (self.pidfile, self.metafile):
                try:
                    path.unlink()
                except OSError:
                    pass


def _parse_max_id(text: str) -> int:
    for token in text.replace("\n", " ").split():
        if token.startswith("max_id=") and token[7:].isdigit():
            return int(token[7:])
    return 0


def resolve_identity(
    project: str, agent_type: str, team: str | None, name: str | None
) -> tuple[str, str]:
    pairs = identity.identities(project, agent_type)
    if team:
        pairs = [(t, a) for t, a in pairs if t == team]
    if name:
        pairs = [(t, a) for t, a in pairs if a == name]
    if not pairs:
        raise AgmsgError(
            "no_identity",
            "no matching codex identity; run actas or pass --team/--name",
            2,
        )
    if len(pairs) > 1:
        raise AgmsgError(
            "ambiguous_identity",
            "multiple identities match; pass --team and --name",
            2,
        )
    return pairs[0]


def run_bridge(options: dict[str, Any]) -> int:
    project = str(Path(options["project"]).resolve())
    team, name = resolve_identity(
        project,
        options.get("type", "codex"),
        options.get("team"),
        options.get("name"),
    )
    if options.get("resolve_only"):
        sys.stdout.write(f"{team}\t{name}\n")
        return 0
    bridge = CodexBridge(
        project,
        team,
        name,
        agent_type=options.get("type", "codex"),
        thread_id=options.get("thread"),
        app_server=options.get("app_server"),
        timeout=options.get("timeout", 300),
        interval=options.get("interval", 2),
        max_wakes=options.get("max_wakes", 0),
        stale_wake_limit=options.get("stale_wake_limit", 1),
        turn_timeout=options.get("turn_timeout", 60),
        inline_inbox=options.get("inline_inbox", False),
    )
    return bridge.run()


def bridge_launcher(
    agent_type: str, project: str, app_server: str, parent_pid: int
) -> int:
    """Wait outside the Codex sandbox and launch bridge requests from the hook."""
    path = request_path(project)
    last = ""
    while _pid_alive(parent_pid):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        if raw and raw != last:
            last = raw
            try:
                item = json.loads(raw)
            except ValueError:
                item = {}
            team = item.get("team")
            name = item.get("name")
            thread_id = item.get("thread")
            endpoint = item.get("app_server") or app_server
            if all(
                isinstance(value, str) and value
                for value in (team, name, thread_id, endpoint)
            ):
                pidfile = bridge_path(team, name, "pid")
                pid = _read_pid(pidfile)
                if not pid or not _pid_alive(pid):
                    log_path = bridge_path(team, name, "log")
                    command_override = os.environ.get("AGMSG_CODEX_BRIDGE_CMD")
                    command = (
                        shlex.split(command_override)
                        if command_override
                        else [
                            plat.python_executable(),
                            str(plat.agmsg_py()),
                            "codex-bridge",
                        ]
                    )
                    command += [
                        "--project",
                        project,
                        "--type",
                        agent_type,
                        "--team",
                        team,
                        "--name",
                        name,
                        "--thread",
                        thread_id,
                        "--app-server",
                        endpoint,
                        "--inline-inbox",
                    ]
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with log_path.open("ab") as log:
                        subprocess.Popen(
                            command,
                            cwd=project,
                            stdin=subprocess.DEVNULL,
                            stdout=log,
                            stderr=log,
                            start_new_session=True,
                        )
        time.sleep(0.2)
    return 0


def _real_codex(shim_target: Path | None = None) -> str:
    override = os.environ.get("AGMSG_REAL_CODEX")
    if override:
        return override
    target = shim_target.resolve() if shim_target and shim_target.exists() else None
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory or ".") / "codex"
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if target is None or resolved != target:
            return str(resolved)
    raise AgmsgError("codex_not_found", "real codex not found on PATH")


def shim_target() -> Path:
    home = os.environ.get("HOME")
    if not home:
        raise AgmsgError("no_home", "HOME is not set")
    return Path(home) / ".agents" / "bin" / "codex"


def _is_our_shim(path: Path) -> bool:
    try:
        return SHIM_MARKER in path.read_text(encoding="utf-8")
    except OSError:
        return False


def install_shim() -> tuple[Path, bool]:
    target = shim_target()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not _is_our_shim(target):
        raise AgmsgError(
            "shim_conflict",
            f"refusing to overwrite existing {target}; move it aside first",
        )
    script = (
        f"#!{plat.python_executable()}\n"
        f'"""{SHIM_MARKER}\nGenerated by agmsg; dispatches to the installed skill.\n"""\n'
        "import os\nimport sys\n"
        f"os.environ['AGMSG_CODEX_SHIM_TARGET'] = {str(target)!r}\n"
        f"os.execv({plat.python_executable()!r}, "
        f"[{plat.python_executable()!r}, {str(plat.agmsg_py())!r}, "
        "'codex-shim', *sys.argv[1:]])\n"
    )
    target.write_text(script, encoding="utf-8")
    target.chmod(0o755)
    first_codex = None
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory or ".") / "codex"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            first_codex = candidate.resolve()
            break
    return target, first_codex == target.resolve()


def remove_shim() -> bool:
    target = shim_target()
    if target.exists() and not _is_our_shim(target):
        raise AgmsgError(
            "shim_conflict",
            f"{target} exists but is not the agmsg shim; leaving it untouched",
        )
    if target.exists():
        target.unlink()
        return True
    return False


_PASSTHROUGH = {
    "app-server",
    "exec",
    "login",
    "logout",
    "mcp",
    "completion",
    "debug",
    "apply",
    "review",
    "sandbox",
    "help",
    "version",
    "--help",
    "--version",
    "-h",
    "-V",
}


def _project_from_args(args: list[str]) -> str:
    project = os.getcwd()
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--cd", "--cwd", "-C") and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif arg.startswith("--cd=") or arg.startswith("--cwd="):
            project = arg.split("=", 1)[1]
            i += 1
        else:
            i += 1
    path = Path(project)
    return str(path.resolve()) if path.is_dir() else str(Path.cwd().resolve())


def _first_non_option(args: list[str]) -> str:
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--cd", "--cwd", "-C"):
            i += 2
        elif arg.startswith("--cd=") or arg.startswith("--cwd="):
            i += 1
        elif arg.startswith("-"):
            if arg in ("--help", "--version", "-h", "-V"):
                return arg
            i += 1
        else:
            return arg
    return ""


def shim_invocation(args: list[str]) -> tuple[str, list[str], dict[str, str]]:
    """Return ``(executable, argv, env)`` for a shim launch."""
    target_env = os.environ.get("AGMSG_CODEX_SHIM_TARGET")
    target = Path(target_env) if target_env else shim_target()
    real = _real_codex(target)
    env = dict(os.environ)
    if (
        env.get("AGMSG_CODEX_SHIM_DISABLE") == "1"
        or env.get("AGMSG_CODEX_BRIDGE") == "1"
    ):
        return real, [real, *args], env
    project = _project_from_args(args)
    from . import delivery

    if delivery.status_mode("codex", project) != "monitor":
        return real, [real, *args], env
    command = _first_non_option(args)
    if command in _PASSTHROUGH:
        return real, [real, *args], env
    monitor_override = env.get("AGMSG_CODEX_MONITOR_CMD")
    if monitor_override:
        prefix = shlex.split(monitor_override)
    else:
        prefix = [plat.python_executable(), str(plat.agmsg_py()), "codex-monitor"]
    monitor_command = "resume" if command == "resume" else "codex"
    forwarded = list(args)
    if command == "resume":
        forwarded.remove("resume")
    env["AGMSG_REAL_CODEX"] = real
    argv = [
        *prefix,
        "--project",
        project,
        "--codex-command",
        monitor_command,
        "--",
        *forwarded,
    ]
    return prefix[0], argv, env


def run_shim(args: list[str]) -> int:
    executable, argv, env = shim_invocation(args)
    os.execve(executable, argv, env)
    return 0


def run_monitor(
    project: str,
    codex_command: str,
    codex_args: list[str],
    socket_override: str | None = None,
) -> int:
    project = str(Path(project).resolve())
    if codex_command not in ("codex", "resume"):
        raise AgmsgError(
            "bad_args", "--codex-command must be 'codex' or 'resume'", 2
        )
    target_env = os.environ.get("AGMSG_CODEX_SHIM_TARGET")
    real = _real_codex(Path(target_env) if target_env else None)
    sock = Path(socket_override).resolve() if socket_override else socket_path(project)
    sock.parent.mkdir(parents=True, exist_ok=True)
    endpoint = f"unix://{sock}"
    log_path = sock.with_suffix(".log")
    pid_path = sock.with_suffix(".pid")
    try:
        socket_ready = stat.S_ISSOCK(sock.stat().st_mode)
    except OSError:
        socket_ready = False
    if not socket_ready:
        try:
            sock.unlink()
        except OSError:
            pass
        with log_path.open("ab") as log:
            child = subprocess.Popen(
                [real, "app-server", "--listen", endpoint],
                cwd=project,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        pid_path.write_text(f"{child.pid}\n", encoding="utf-8")
        for _ in range(50):
            try:
                socket_ready = stat.S_ISSOCK(sock.stat().st_mode)
            except OSError:
                socket_ready = False
            if socket_ready:
                break
            time.sleep(0.1)
    if not socket_ready:
        raise AgmsgError(
            "app_server_failed",
            f"app-server socket did not appear: {sock}; see {log_path}",
        )
    from . import delivery

    delivery.apply("monitor", "codex", project)
    try:
        request_path(project).unlink()
    except OSError:
        pass
    env = dict(os.environ)
    env.update(
        {
            "AGMSG_CODEX_BRIDGE": "1",
            "AGMSG_CODEX_BRIDGE_APP_SERVER": endpoint,
            "AGMSG_CODEX_BRIDGE_LAUNCHER": "1",
            "AGMSG_REAL_CODEX": real,
        }
    )
    launcher_override = env.get("AGMSG_CODEX_BRIDGE_LAUNCHER_CMD")
    launcher = (
        shlex.split(launcher_override)
        if launcher_override
        else [
            plat.python_executable(),
            str(plat.agmsg_py()),
            "codex-bridge-launcher",
        ]
    )
    subprocess.Popen(
        [*launcher, "codex", project, endpoint, str(os.getpid())],
        cwd=project,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    argv = [real]
    if codex_command == "resume":
        argv.append("resume")
    argv += ["--remote", endpoint, *codex_args]
    os.chdir(project)
    os.execve(real, argv, env)
    return 0


def stop_bridges(project: str) -> int:
    killed = 0
    for team, name in identity.identities(project, "codex"):
        pidfile = bridge_path(team, name, "pid")
        pid = _read_pid(pidfile)
        if pid and _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                killed += 1
            except OSError:
                pass
        for suffix in ("pid", "meta", "log"):
            try:
                bridge_path(team, name, suffix).unlink()
            except OSError:
                pass
    try:
        request_path(project).unlink()
    except OSError:
        pass
    return killed
