#!/usr/bin/env python3
"""A stand-in for Empires of the Undergrowth with a toy "multiplayer mod", to test the bot end to
end (real screenshots, real mouse and keyboard) without the real game. Needs pygame-ce.

The layout loosely follows the real game: the surface minimap bottom-left (your ants green,
enemies red), the control panel bottom-middle with pheromone groups I and II, the nest minimap
that moves the camera into the nest, the Brood menu on O, the pause menu on Escape.

  practice_game.py --role host --game-port 7777          # this copy hosts
  practice_game.py --role join                           # this copy joins (type the host's address)

Faults for testing the bot's checks (on the joining copy):
  --fault desync      shows Victory when it actually lost
  --fault freeze:30   stops drawing 30 s into the match
  --fault crash:30    exits 30 s into the match
  --fault drop:30     (host) cuts the connection 30 s into the match
"""
import argparse
import json
import math
import os
import random
import socket
import sys
import threading
import time

import pygame

TITLE = "Empires of the Undergrowth (practice)"
BTN = (0.24, 0.07)
MENU = {"campaign": (0.5, 0.42), "multiplayer": (0.5, 0.52), "settings": (0.5, 0.62), "quit": (0.5, 0.72)}
LOBBY = {"host": (0.35, 0.33), "join": (0.65, 0.33), "address": (0.65, 0.45), "start": (0.5, 0.75),
         "back": (0.12, 0.9)}
MINIMAP = (0.01, 0.60, 0.21, 0.98)
NEST_MM = (0.23, 0.85, 0.31, 0.98)
PANEL_Y = 0.83
GROUP_POS = {"nest": (0.40, 0.915), 1: (0.50, 0.915), 2: (0.58, 0.915)}
ICON = (0.06, 0.11)
NEST_SPOTS = [(0.3, 0.35), (0.5, 0.5), (0.7, 0.35)]
BROOD = {"worker": (0.86, 0.35), "soldier": (0.86, 0.47)}
PAUSE = {"resume": (0.5, 0.45), "quit": (0.5, 0.56)}
CONFIRM_YES = (0.5, 0.72)
END_TEXT, END_CONTINUE = (0.5, 0.35), (0.5, 0.6)
DISC_TEXT, DISC_OK = (0.5, 0.4), (0.5, 0.55)
NESTS = {"host": (0.18, 0.78), "join": (0.82, 0.22)}
GREEN, RED = (60, 220, 60), (230, 50, 40)


def other(side):
    return "join" if side == "host" else "host"


# --- the simulation (runs on the host copy) ---------------------------------------------------

class Colony:
    def __init__(self, side):
        self.side = side
        self.nest = NESTS[side]
        self.food, self.workers, self.home, self.hp = 40.0, 6.0, 4.0, 100.0
        self.group = {1: 0.0, 2: 0.0}
        self.pos = {1: self.nest, 2: self.nest}
        self.marker = {1: None, 2: None}
        self.chambers = {"worker": 1, "soldier": 0}
        self.timers = {"worker": 0.0, "soldier": 0.0}

    def state(self):
        return {"food": round(self.food), "workers": round(self.workers, 1), "home": round(self.home, 1),
                "hp": round(self.hp, 1), "group": {str(k): round(v, 2) for k, v in self.group.items()},
                "pos": {str(k): v for k, v in self.pos.items()},
                "marker": {str(k): v for k, v in self.marker.items()}, "chambers": dict(self.chambers)}


class Sim:
    def __init__(self):
        self.c = {s: Colony(s) for s in ("host", "join")}
        self.t, self.winner, self.log = 0.0, None, []

    def command(self, side, cmd):
        c = self.c[side]
        kind = cmd.get("cmd")
        if kind == "build":
            cost = 15 if cmd["kind"] == "worker" else 25
            if c.food >= cost:
                c.food -= cost
                c.chambers[cmd["kind"]] += 1
        elif kind == "marker":
            c.marker[int(cmd["group"])] = (float(cmd["x"]), float(cmd["y"]))
        elif kind == "assign":
            c.group[1] += c.home
            c.home = 0.0
        self.log.append((round(self.t, 1), side, cmd))

    def step(self, dt):
        if self.winner:
            return
        self.t += dt
        for c in self.c.values():
            c.food += c.workers * 0.3 * dt
            for kind, n in c.chambers.items():
                if not n:
                    continue
                c.timers[kind] += dt * n
                period, cost = (6.0, 4.0) if kind == "worker" else (4.0, 6.0)
                while c.timers[kind] >= period:
                    c.timers[kind] -= period
                    if c.food >= cost:
                        c.food -= cost
                        if kind == "worker":
                            c.workers += 1
                        else:
                            c.home += 1
            for g in (1, 2):
                tx, ty = c.marker[g] or c.nest
                x, y = c.pos[g]
                d = math.hypot(tx - x, ty - y)
                step = 0.06 * dt
                c.pos[g] = (tx, ty) if d <= step else (x + (tx - x) * step / d, y + (ty - y) * step / d)
        a, b = self.c["host"], self.c["join"]

        def units(c):
            return [("home", c.nest), (1, c.pos[1]), (2, c.pos[2])]

        def count(c, u):
            return c.home if u == "home" else c.group[u]

        def take(c, u, n):
            if u == "home":
                c.home = max(0.0, c.home - n)
            else:
                c.group[u] = max(0.0, c.group[u] - n)

        for ua, pa in units(a):
            for ub, pb in units(b):
                na, nb = count(a, ua), count(b, ub)
                if na > 0 and nb > 0 and math.dist(pa, pb) < 0.07:
                    take(a, ua, 0.12 * nb * dt)
                    take(b, ub, 0.12 * na * dt)
        for c, e in ((a, b), (b, a)):
            defenders = c.home + sum(c.group[g] for g in (1, 2) if math.dist(c.pos[g], c.nest) < 0.07)
            attackers = sum(e.group[g] for g in (1, 2) if math.dist(e.pos[g], c.nest) < 0.07)
            if attackers > 0.5 and defenders < 0.5:
                c.hp -= attackers * 0.5 * dt
                c.workers = max(0.0, c.workers - attackers * 0.03 * dt)
            if c.hp <= 0:
                self.winner = e.side


# --- the game window ----------------------------------------------------------------------------

class Game:
    def __init__(self, args):
        self.args = args
        self.side = args.role
        w, h = (int(v) for v in args.size.split("x"))
        self.w, self.h = w, h
        pygame.init()
        self.win = pygame.display.set_mode((w, h))
        pygame.display.set_caption(TITLE)
        self.font = pygame.font.Font(None, max(18, h // 32))
        self.big = pygame.font.Font(None, max(40, h // 9))
        self.screen = "menu"
        self.pause = self.confirm = self.brood = False
        self.selected, self.build_kind = 1, None
        self.address, self.address_focus = "", False
        self.sock, self.conn_lock, self.peer_ok = None, threading.Lock(), False
        self.hosting = False
        self.sim = None
        self.state = None
        self.match_t0 = None
        self.loading_until = 0.0
        self.end_seen = None
        self.drag_from = None
        self.fault, self.fault_t = (args.fault.split(":") + ["0"])[:2] if args.fault else (None, "0")
        self.fault_t = float(self.fault_t)
        self.frozen = False
        self.inbox = []
        self.last_send = 0.0
        self.rng = random.Random(1)

    # helpers
    def px(self, fx, fy):
        return int(fx * self.w), int(fy * self.h)

    def rect(self, centre, size):
        cx, cy = self.px(*centre)
        w, h = int(size[0] * self.w), int(size[1] * self.h)
        return pygame.Rect(cx - w // 2, cy - h // 2, w, h)

    def hit(self, pos, centre, size=BTN):
        return self.rect(centre, size).collidepoint(pos)

    def mm_rect(self, box):
        x0, y0 = self.px(box[0], box[1])
        x1, y1 = self.px(box[2], box[3])
        return pygame.Rect(x0, y0, x1 - x0, y1 - y0)

    def button(self, centre, label, enabled=True, size=BTN):
        r = self.rect(centre, size)
        pygame.draw.rect(self.win, (92, 70, 40) if enabled else (60, 55, 50), r, border_radius=6)
        pygame.draw.rect(self.win, (200, 170, 110), r, 2, border_radius=6)
        t = self.font.render(label, True, (240, 230, 200) if enabled else (130, 125, 115))
        self.win.blit(t, t.get_rect(center=r.center))

    def text(self, s, centre, font=None, colour=(235, 228, 205)):
        t = (font or self.font).render(s, True, colour)
        self.win.blit(t, t.get_rect(center=self.px(*centre)))

    # networking ("the multiplayer mod")
    def send(self, msg):
        with self.conn_lock:
            s = self.sock
        if s is None:
            return
        try:
            s.sendall((json.dumps(msg) + "\n").encode())
        except OSError:
            self.lost()

    def lost(self):
        with self.conn_lock:
            s, self.sock = self.sock, None
        if s:
            try:
                s.close()
            except OSError:
                pass
        if self.screen in ("match", "nest", "loading"):
            self.screen = "disconnected"
            self.pause = self.confirm = self.brood = False
        self.peer_ok = False

    def reader(self, s):
        try:
            for line in s.makefile("rb"):
                self.inbox.append(json.loads(line))
        except (OSError, ValueError):
            pass
        self.inbox.append({"t": "_lost"})

    def host_game(self):
        if self.hosting:
            return
        self.hosting = True
        srv = socket.create_server(("", self.args.game_port))

        def accept():
            conn, _ = srv.accept()
            with self.conn_lock:
                self.sock = conn
            self.peer_ok = True
            self.reader(conn)

        threading.Thread(target=accept, daemon=True).start()

    def join_game(self):
        addr = self.address.strip()
        host, _, port = addr.partition(":")
        try:
            s = socket.create_connection((host, int(port or self.args.game_port)), timeout=3)
        except (OSError, ValueError):
            self.address = "connection failed"
            return
        with self.conn_lock:
            self.sock = s
        self.peer_ok = True
        threading.Thread(target=self.reader, args=(s,), daemon=True).start()

    def start_match(self):
        self.screen = "loading"
        self.loading_until = time.monotonic() + 1.5
        self.sim = Sim() if self.side == "host" else None
        self.state, self.end_seen = None, None
        self.pause = self.confirm = self.brood = False
        self.selected, self.build_kind = 1, None

    def command(self, cmd):
        if self.side == "host":
            self.sim.command("host", cmd)
        else:
            self.send({"t": "cmd", **cmd})

    # events
    def on_click(self, pos, button):
        s = self.screen
        if s == "menu" and button == 1:
            if self.hit(pos, MENU["multiplayer"]):
                self.screen = "lobby"
            elif self.hit(pos, MENU["quit"]):
                sys.exit(0)
        elif s == "lobby" and button == 1:
            self.address_focus = False
            if self.hit(pos, LOBBY["host"]) and self.side == "host":
                self.host_game()
            elif self.hit(pos, LOBBY["join"]) and self.side == "join":
                self.address_focus = True
            elif self.hit(pos, LOBBY["address"]):
                self.address_focus = True
            elif self.hit(pos, LOBBY["start"]) and self.side == "host" and self.peer_ok:
                self.send({"t": "start"})
                self.start_match()
            elif self.hit(pos, LOBBY["back"]):
                self.screen = "menu"
        elif s in ("victory", "defeat") and button == 1 and self.hit(pos, END_CONTINUE):
            self.lost()
            self.screen = "menu"
        elif s == "disconnected" and button == 1 and self.hit(pos, DISC_OK):
            self.screen = "menu"
        elif s in ("match", "nest"):
            self.on_match_click(pos, button)

    def on_match_click(self, pos, button):
        if self.pause:
            if self.confirm and button == 1 and self.hit(pos, CONFIRM_YES):
                self.lost()
                self.screen, self.pause, self.confirm = "menu", False, False
            elif button == 1 and self.hit(pos, PAUSE["quit"]):
                self.confirm = True
            elif button == 1 and self.hit(pos, PAUSE["resume"]):
                self.pause = self.confirm = False
            return
        mm = self.mm_rect(MINIMAP)
        if mm.collidepoint(pos):
            fx, fy = (pos[0] - mm.x) / mm.w, (pos[1] - mm.y) / mm.h
            if button == 3:
                self.command({"cmd": "marker", "group": self.selected, "x": fx, "y": fy})
            else:
                self.screen = "match"
            return
        if self.mm_rect(NEST_MM).collidepoint(pos) and button == 1:
            self.screen = "nest"
            return
        for g in (1, 2):
            if self.hit(pos, GROUP_POS[g], ICON) and button == 1:
                self.selected = g
                return
        if self.screen == "nest" and button == 1:
            if self.brood:
                for kind, c in BROOD.items():
                    if self.hit(pos, c, (0.2, 0.08)):
                        self.build_kind = kind
                        return
            if self.build_kind:
                for c in NEST_SPOTS:
                    if self.hit(pos, c, (0.12, 0.1)):
                        self.command({"cmd": "build", "kind": self.build_kind})
                        return

    def on_key(self, ev):
        if self.screen == "lobby" and self.address_focus:
            if ev.key == pygame.K_RETURN:
                self.address_focus = False
                self.join_game()
            elif ev.key == pygame.K_BACKSPACE:
                self.address = self.address[:-1]
            elif ev.key == pygame.K_a and ev.mod & pygame.KMOD_CTRL:
                self.address = ""
            elif ev.unicode and ev.unicode.isprintable():
                self.address += ev.unicode
            return
        if self.screen in ("match", "nest"):
            if ev.key == pygame.K_ESCAPE:
                if self.brood:
                    self.brood, self.build_kind = False, None
                elif self.pause:
                    self.pause = self.confirm = False
                else:
                    self.pause = True
            elif ev.key == pygame.K_o and self.screen == "nest" and not self.pause:
                self.brood = not self.brood
                if not self.brood:
                    self.build_kind = None
        elif self.screen == "lobby" and ev.key == pygame.K_ESCAPE:
            self.screen = "menu"

    # per frame
    def update(self):
        now = time.monotonic()
        while self.inbox:
            m = self.inbox.pop(0)
            t = m.get("t")
            if t == "_lost":
                self.lost()
            elif t == "start" and self.side == "join":
                self.start_match()
            elif t == "cmd" and self.sim:
                self.sim.command("join", m)
            elif t == "state":
                self.state = m["s"]
            elif t == "end" and self.side == "join":
                self.end_seen = m["winner"]
        if self.screen == "loading" and now >= self.loading_until:
            self.screen, self.match_t0 = "match", now
        if self.screen not in ("match", "nest"):
            return
        mt = now - self.match_t0
        if self.fault == "crash" and self.side == "join" and mt >= self.fault_t:
            os._exit(3)
        if self.fault == "freeze" and self.side == "join" and mt >= self.fault_t:
            self.frozen = True
        if self.fault == "drop" and self.side == "host" and mt >= self.fault_t:
            self.fault = None
            self.lost()
            return
        if self.side == "host":
            self.sim.step(min(0.1, 1 / 30) * self.args.speed)
            self.state = {s: c.state() for s, c in self.sim.c.items()}
            if now - self.last_send > 0.1:
                self.send({"t": "state", "s": self.state})
                self.last_send = now
            if self.sim.winner:
                self.send({"t": "end", "winner": self.sim.winner})
                self.end_seen = self.sim.winner
        if self.end_seen:
            won = self.end_seen == self.side
            if self.fault == "desync" and self.side == "join":
                won = True
            self.screen = "victory" if won else "defeat"
            self.pause = self.confirm = self.brood = False

    # drawing
    def draw(self):
        if self.frozen:
            return
        w = self.win
        s = self.screen
        if s == "menu":
            w.fill((24, 30, 22))
            logo = self.rect((0.5, 0.18), (0.5, 0.13))
            pygame.draw.rect(w, (70, 52, 30), logo, border_radius=10)
            self.text("EMPIRES OF THE UNDERGROWTH", (0.5, 0.16), colour=(230, 200, 120))
            self.text("practice arena", (0.5, 0.21), colour=(170, 190, 150))
            for key, label in (("campaign", "Campaign"), ("multiplayer", "Multiplayer"),
                               ("settings", "Settings"), ("quit", "Quit")):
                self.button(MENU[key], label)
        elif s == "lobby":
            w.fill((20, 26, 30))
            self.text("Multiplayer (practice mod)", (0.5, 0.12), self.big)
            self.button(LOBBY["host"], "Host")
            self.button(LOBBY["join"], "Join")
            box = self.rect(LOBBY["address"], (0.3, 0.06))
            pygame.draw.rect(w, (230, 230, 225), box)
            pygame.draw.rect(w, (255, 200, 80) if self.address_focus else (90, 90, 90), box, 2)
            t = self.font.render(self.address or "host address", True, (20, 20, 20) if self.address else (130, 130, 130))
            w.blit(t, t.get_rect(midleft=(box.x + 8, box.centery)))
            status = ("Hosting: 2/2 players" if self.hosting and self.peer_ok else "Hosting: waiting for a player"
                      if self.hosting else "Joined: waiting for the host" if self.peer_ok else "")
            self.text(status, (0.5, 0.6))
            if self.side == "host":
                self.button(LOBBY["start"], "Start match", enabled=self.peer_ok)
            self.button(LOBBY["back"], "Back", size=(0.14, 0.06))
        elif s == "loading":
            w.fill((8, 8, 8))
            self.text("Loading...", (0.5, 0.5), self.big)
        elif s in ("match", "nest"):
            self.draw_match()
        elif s in ("victory", "defeat"):
            w.fill((14, 18, 14))
            panel = self.rect((0.5, 0.45), (0.5, 0.45))
            pygame.draw.rect(w, (40, 34, 24), panel, border_radius=12)
            self.text("VICTORY" if s == "victory" else "DEFEAT", END_TEXT, self.big,
                      (240, 200, 70) if s == "victory" else (220, 70, 60))
            self.button(END_CONTINUE, "Continue")
        elif s == "disconnected":
            w.fill((30, 18, 18))
            self.text("Connection to the other player was lost", DISC_TEXT)
            self.button(DISC_OK, "OK", size=(0.12, 0.06))
        pygame.display.flip()

    def dots(self, rect, c, colour, t, radius, scale):
        r = random.Random(hash(c["hp"]) % 7)  # stable layout, jitter from time
        groups = [(NESTS_OF[id(c)], c["home"])] + [(tuple(c["pos"][g]), c["group"][g]) for g in ("1", "2")]
        groups.append((NESTS_OF[id(c)], c["workers"]))
        for (gx, gy), n in groups:
            for i in range(min(int(round(n)), 40)):
                a = i * 2.39996 + t * (0.8 + 0.1 * (i % 5))
                d = 0.012 + 0.004 * math.sqrt(i)
                x = gx + math.cos(a) * d * scale
                y = gy + math.sin(a) * d * scale
                pygame.draw.circle(self.win, colour, (rect.x + int(x * rect.w), rect.y + int(y * rect.h)), radius)

    def draw_match(self):
        w, t = self.win, time.monotonic()
        st = self.state
        me, them = self.side, other(self.side)
        world = pygame.Rect(0, 0, self.w, int(PANEL_Y * self.h))
        if self.screen == "match":
            w.fill((46, 70, 38), world)
            for i in range(30):  # swaying grass so the picture keeps moving
                gx = (i * 97) % self.w
                gy = (i * 53) % world.h
                sway = int(4 * math.sin(t * 1.7 + i))
                pygame.draw.line(w, (70, 105, 52), (gx, gy), (gx + sway, gy - 14), 2)
        else:
            w.fill((70, 48, 30), world)
            pygame.draw.circle(w, (210, 170, 90), self.px(0.5, 0.25), int(0.03 * self.h))  # the queen
            for c in NEST_SPOTS:
                pygame.draw.ellipse(w, (150, 112, 70), self.rect(c, (0.12, 0.1)))
            if st:
                ch = st[me]["chambers"]
                self.text(f"Worker chambers {ch['worker']}   Soldier chambers {ch['soldier']}", (0.5, 0.7))
            for i in range(12):
                a = t * 1.3 + i
                pygame.draw.circle(w, (25, 20, 15), self.px(0.5 + 0.25 * math.cos(a), 0.45 + 0.15 * math.sin(a * 0.7)), 4)
            if self.brood:
                pygame.draw.rect(w, (40, 30, 22), self.rect((0.86, 0.41), (0.24, 0.3)), border_radius=8)
                for kind, c in BROOD.items():
                    self.button(c, f"{kind.title()} chamber", size=(0.2, 0.08))
                    if self.build_kind == kind:
                        pygame.draw.rect(w, (255, 220, 90), self.rect(c, (0.2, 0.08)), 3)
        if st and self.screen == "match":
            NESTS_OF.clear()
            NESTS_OF[id(st[me])], NESTS_OF[id(st[them])] = NESTS[me], NESTS[them]
            self.dots(world, st[me], (20, 20, 20), t, 4, 3)
            self.dots(world, st[them], (150, 30, 25), t, 4, 3)
        # bottom panel
        panel = pygame.Rect(0, int(PANEL_Y * self.h), self.w, self.h - int(PANEL_Y * self.h))
        pygame.draw.rect(w, (52, 38, 24), panel)
        pygame.draw.rect(w, (150, 120, 70), panel, 3)
        if st:
            self.text(f"Food {st[me]['food']}", (0.9, 0.88))
            self.text(f"Nest {st[me]['hp']:.0f}%", (0.9, 0.94))
        labels = {"nest": "Nest", 1: "I", 2: "II"}
        for g, c in GROUP_POS.items():
            r = self.rect(c, ICON)
            pygame.draw.rect(w, (88, 66, 40), r, border_radius=6)
            pygame.draw.rect(w, (255, 220, 90) if g == self.selected else (170, 140, 90), r, 2, border_radius=6)
            self.text(labels[g], (c[0], c[1] - 0.02))
            if st:
                n = st[me]["home"] if g == "nest" else st[me]["group"][str(g)]
                self.text(str(int(round(n))), (c[0], c[1] + 0.03), colour=(200, 200, 180))
        mm = self.mm_rect(MINIMAP)
        pygame.draw.rect(w, (28, 40, 28), mm)
        pygame.draw.rect(w, (150, 120, 70), mm, 2)
        nm = self.mm_rect(NEST_MM)
        pygame.draw.rect(w, (60, 42, 28), nm)
        pygame.draw.rect(w, (150, 120, 70), nm, 2)
        if st:
            for side in (me, them):
                nx, ny = NESTS[side]
                pygame.draw.rect(w, (110, 80, 45), (mm.x + int(nx * mm.w) - 5, mm.y + int(ny * mm.h) - 5, 10, 10))
            NESTS_OF.clear()
            NESTS_OF[id(st[me])], NESTS_OF[id(st[them])] = NESTS[me], NESTS[them]
            self.dots(mm, st[me], GREEN, t, 2, 1)
            self.dots(mm, st[them], RED, t, 2, 1)
            for g in ("1", "2"):
                m = st[me]["marker"][g]
                if m:
                    pygame.draw.circle(w, (255, 230, 120), (mm.x + int(m[0] * mm.w), mm.y + int(m[1] * mm.h)), 5, 1)
        if self.pause:
            shade = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 170))
            w.blit(shade, (0, 0))
            self.text("Paused", (0.5, 0.33), self.big)
            self.button(PAUSE["resume"], "Resume")
            self.button(PAUSE["quit"], "Quit to main menu")
            if self.confirm:
                self.text("Leave the match?", (0.5, 0.65))
                self.button(CONFIRM_YES, "Yes, leave", size=(0.16, 0.06))

    def run(self):
        clock = pygame.time.Clock()
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                if ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1 and self.screen in ("match", "nest") and not self.pause \
                            and self.hit(ev.pos, GROUP_POS["nest"], ICON):
                        self.drag_from = "nest"
                    else:
                        self.on_click(ev.pos, ev.button)
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.drag_from:
                    if self.hit(ev.pos, GROUP_POS[1], ICON) and self.screen in ("match", "nest"):
                        self.command({"cmd": "assign"})
                    self.drag_from = None
                elif ev.type == pygame.KEYDOWN:
                    self.on_key(ev)
            self.update()
            self.draw()
            clock.tick(30)


NESTS_OF = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=("host", "join"), required=True)
    ap.add_argument("--size", default="1280x800")
    ap.add_argument("--game-port", type=int, default=7777)
    ap.add_argument("--speed", type=float, default=1.0, help="simulation speed (host)")
    ap.add_argument("--fault", default="", help="desync | freeze:SECONDS | crash:SECONDS | drop:SECONDS")
    args = ap.parse_args()
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    Game(args).run()


if __name__ == "__main__":
    main()
