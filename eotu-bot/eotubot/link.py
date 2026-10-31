"""The two bots talk over one TCP connection: one JSON message per line.

The host PC listens; the joining PC connects to it and reconnects by itself if the line drops.
"""
import json
import platform
import socket
import threading
import time

from . import VERSION

PROTO = 1


class Link:
    def __init__(self, role, port, host=None, log=print, ping_every=10.0, dead_after=45.0, name=None):
        assert role in ("host", "join")
        self.role, self.port, self.host = role, int(port), host
        self.log = log
        self.ping_every, self.dead_after = float(ping_every), float(dead_after)
        self.name = name or platform.node() or role
        self.sock = None
        self.peer_addr = None
        self.peer_hello = None
        self.server = None
        self.closed = False
        self.connects = 0
        self.last_rx = 0.0
        self.inbox = []
        self.lock = threading.Lock()
        self.cv = threading.Condition()

    # -- connection --------------------------------------------------------------------------
    def start(self):
        if self.role == "host":
            self.server = socket.create_server(("", self.port), reuse_port=False)
            self.server.settimeout(1.0)
            self.port = self.server.getsockname()[1]
            threading.Thread(target=self._accept_loop, name="link-accept", daemon=True).start()
        else:
            threading.Thread(target=self._connect_loop, name="link-connect", daemon=True).start()
        threading.Thread(target=self._ping_loop, name="link-ping", daemon=True).start()
        return self

    def _accept_loop(self):
        while not self.closed:
            try:
                conn, addr = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self._attach(conn, addr)

    def _connect_loop(self):
        warned = 0.0
        while not self.closed:
            if self.sock is None:
                try:
                    s = socket.create_connection((self.host, self.port), timeout=5)
                    self._attach(s, (self.host, self.port))
                except OSError as e:
                    if time.monotonic() - warned > 30:
                        self.log(f"Link: can't reach the host bot at {self.host}:{self.port} yet ({e}); retrying")
                        warned = time.monotonic()
                    time.sleep(2)
                    continue
            time.sleep(0.5)

    def _attach(self, conn, addr):
        conn.settimeout(None)
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        with self.lock:
            old, self.sock, self.peer_addr = self.sock, conn, addr[0]
        if old is not None:
            _close(old)
        self.connects += 1
        self.last_rx = time.monotonic()
        threading.Thread(target=self._reader, args=(conn,), name="link-read", daemon=True).start()
        self.send("hello", bot=VERSION, proto=PROTO, name=self.name, os=platform.system())

    def _reader(self, conn):
        try:
            with conn.makefile("rb") as f:
                for line in f:
                    self.last_rx = time.monotonic()
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    op = msg.get("op")
                    if op == "ping":
                        continue
                    if op == "hello":
                        self.peer_hello = msg
                        note = "" if msg.get("proto") == PROTO else " (different bot version: update both PCs)"
                        self.log(f"Link: connected to {msg.get('name')} ({msg.get('os')}, bot {msg.get('bot')}) "
                                 f"at {self.peer_addr}{note}")
                    with self.cv:
                        self.inbox.append(msg)
                        self.cv.notify_all()
        except OSError:
            pass
        finally:
            dropped = False
            with self.lock:
                if self.sock is conn:
                    self.sock = None
                    dropped = True
            _close(conn)
            if dropped and not self.closed:
                self.log("Link: the other bot disconnected")
            with self.cv:
                self.cv.notify_all()

    def _ping_loop(self):
        while not self.closed:
            time.sleep(self.ping_every)
            if self.sock is None:
                continue
            self.send("ping")
            if time.monotonic() - self.last_rx > self.dead_after:
                self.log("Link: no word from the other bot for a while; reconnecting")
                with self.lock:
                    s, self.sock = self.sock, None
                if s is not None:
                    _close(s)

    @property
    def connected(self):
        return self.sock is not None

    def wait_connected(self, timeout=None, on_wait=None):
        end = None if timeout is None else time.monotonic() + timeout
        last = time.monotonic()
        while not self.connected:
            if end is not None and time.monotonic() >= end:
                return False
            if on_wait and time.monotonic() - last >= 30:
                on_wait()
                last = time.monotonic()
            time.sleep(0.2)
        return True

    def close(self):
        self.closed = True
        with self.lock:
            s, self.sock = self.sock, None
        if s is not None:
            _close(s)
        if self.server is not None:
            _close(self.server)

    # -- messages ----------------------------------------------------------------------------
    def send(self, op, **data):
        msg = dict(data)
        msg["op"], msg["at"] = op, time.time()
        line = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        with self.lock:
            s = self.sock
            if s is None:
                return False
            try:
                s.sendall(line)
                return True
            except OSError:
                self.sock = None
        _close(s)
        return False

    def get(self, ops, timeout=0.0, match=None, check=None):
        """The first waiting message whose op is in `ops` (and, if given, whose 'match' equals
        `match`), waiting up to `timeout` seconds (None = forever). `check` runs every second
        while waiting (the bot uses it to notice stop requests)."""
        ops = {ops} if isinstance(ops, str) else set(ops)
        end = None if timeout is None else time.monotonic() + timeout
        with self.cv:
            while True:
                for i, m in enumerate(self.inbox):
                    if m.get("op") in ops and (match is None or m.get("match") == match):
                        return self.inbox.pop(i)
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    return None
                self.cv.wait(1.0 if left is None else min(left, 1.0))
                if check:
                    self.cv.release()
                    try:
                        check()
                    finally:
                        self.cv.acquire()

    def take_all(self, op, match=None):
        with self.cv:
            keep, out = [], []
            for m in self.inbox:
                if m.get("op") == op and (match is None or m.get("match") == match):
                    out.append(m)
                else:
                    keep.append(m)
            self.inbox = keep
        return out

    def forget_except(self, match):
        """Drop leftovers from earlier matches."""
        with self.cv:
            self.inbox = [m for m in self.inbox if m.get("match") in (None, match)]


def _close(s):
    try:
        s.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        s.close()
    except OSError:
        pass
