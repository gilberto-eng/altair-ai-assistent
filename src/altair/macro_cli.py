from __future__ import annotations

"""
Macro recorder/player (CLI).

Requisitos:
  pip install pynput

Uso:
  python -m altair.macro_cli record --out macro.json
  python -m altair.macro_cli play --in macro.json -n 5 --speed 1.5

Controles (play):
  ESC cancela, F8 pausa/retoma, mover mouse para (0,0) cancela
"""

import argparse
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def _require_pynput() -> None:
    try:
        import pynput  # noqa: F401
    except Exception as exc:
        raise RuntimeError("Dependencia ausente: instale com pip install pynput") from exc


def _now() -> float:
    return time.perf_counter()


def _button_to_str(btn) -> str:
    name = getattr(btn, "name", None)
    if name:
        return str(name)
    return str(btn).replace("Button.", "").strip()


def _str_to_button(mouse_mod, s: str):
    s = (s or "").strip().lower()
    for cand in ("left", "right", "middle"):
        if s == cand:
            return getattr(mouse_mod.Button, cand)
    return mouse_mod.Button.left


def _key_to_str(key) -> str:
    if hasattr(key, "char") and key.char is not None:
        return str(key.char)
    name = getattr(key, "name", None)
    if name:
        return f"Key.{name}"
    s = str(key)
    if s.startswith("Key."):
        return s
    return s


def _str_to_key(keyboard_mod, s: str):
    s = str(s)
    if s.startswith("Key."):
        name = s.split(".", 1)[1]
        return getattr(keyboard_mod.Key, name)
    return s


@dataclass
class MacroEvent:
    type: str
    t: float
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "t": float(self.t), "data": dict(self.data)}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "MacroEvent":
        return MacroEvent(type=str(d.get("type", "")), t=float(d.get("t", 0.0)), data=dict(d.get("data", {}) or {}))


class MacroRecorder:
    def __init__(self, record_moves: bool = True, move_interval_s: float = 0.03) -> None:
        _require_pynput()
        from pynput import keyboard, mouse

        self._keyboard_mod = keyboard
        self._mouse_mod = mouse
        self._record_moves = bool(record_moves)
        self._move_interval_s = max(0.0, float(move_interval_s))

        self._events: List[MacroEvent] = []
        self._start_t: Optional[float] = None
        self._last_move_t: float = 0.0
        self._running = False
        self._kb_listener = None
        self._ms_listener = None

    @property
    def events(self) -> List[MacroEvent]:
        return list(self._events)

    def start_recording(self) -> None:
        if self._running:
            return
        self._running = True
        self._events = []
        self._start_t = _now()
        self._last_move_t = 0.0

        def rel_t() -> float:
            assert self._start_t is not None
            return _now() - self._start_t

        def on_move(x, y):
            if not self._record_moves:
                return
            t = rel_t()
            if t - self._last_move_t < self._move_interval_s:
                return
            self._last_move_t = t
            self._events.append(MacroEvent("mouse_move", t, {"x": int(x), "y": int(y)}))

        def on_click(x, y, button, pressed):
            t = rel_t()
            self._events.append(
                MacroEvent("click", t, {"x": int(x), "y": int(y), "button": _button_to_str(button), "pressed": bool(pressed)})
            )

        def on_press(key):
            t = rel_t()
            self._events.append(MacroEvent("key_down", t, {"key": _key_to_str(key)}))

        def on_release(key):
            t = rel_t()
            self._events.append(MacroEvent("key_up", t, {"key": _key_to_str(key)}))

        self._ms_listener = self._mouse_mod.Listener(on_move=on_move, on_click=on_click)
        self._kb_listener = self._keyboard_mod.Listener(on_press=on_press, on_release=on_release)
        self._ms_listener.start()
        self._kb_listener.start()

    def stop_recording(self) -> List[MacroEvent]:
        if not self._running:
            return list(self._events)
        self._running = False
        try:
            if self._ms_listener:
                self._ms_listener.stop()
            if self._kb_listener:
                self._kb_listener.stop()
        finally:
            self._ms_listener = None
            self._kb_listener = None
        self._events.sort(key=lambda e: e.t)
        return list(self._events)

    def to_json_obj(self) -> Dict[str, Any]:
        return {"version": 1, "record_moves": self._record_moves, "events": [e.to_dict() for e in self._events]}

    def save(self, path: Union[str, Path]) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_json_obj(), ensure_ascii=False, indent=2), encoding="utf-8")
        return out


class MacroPlayer:
    def __init__(self, failsafe_corner: bool = True) -> None:
        _require_pynput()
        from pynput import keyboard, mouse

        self._keyboard_mod = keyboard
        self._mouse_mod = mouse
        self._kb = keyboard.Controller()
        self._ms = mouse.Controller()
        self._failsafe_corner = bool(failsafe_corner)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.clear()
        self._hotkey_listener = None

    def _sleep_coop(self, seconds: float) -> None:
        end = time.time() + max(0.0, seconds)
        while time.time() < end:
            if self._stop.is_set():
                return
            while self._pause.is_set() and not self._stop.is_set():
                time.sleep(0.05)
            time.sleep(0.005)

    def _start_hotkeys(self) -> None:
        def on_press(key):
            if key == self._keyboard_mod.Key.esc:
                self._stop.set()
                return False
            if key == self._keyboard_mod.Key.f8:
                if self._pause.is_set():
                    self._pause.clear()
                    print("[play] retomado (F8)")
                else:
                    self._pause.set()
                    print("[play] pausado (F8)")
            return None

        self._hotkey_listener = self._keyboard_mod.Listener(on_press=on_press)
        self._hotkey_listener.start()

    def _stop_hotkeys(self) -> None:
        if self._hotkey_listener:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
        self._hotkey_listener = None

    def play_macro(self, events: List[MacroEvent], repeticoes: int = 1, velocidade: float = 1.0, log: bool = True) -> None:
        repeticoes = max(1, int(repeticoes))
        velocidade = float(velocidade)
        if velocidade <= 0:
            velocidade = 1.0

        events = sorted(list(events), key=lambda e: e.t)
        if not events:
            print("Nada para executar.")
            return

        self._stop.clear()
        self._pause.clear()
        self._start_hotkeys()
        try:
            for i in range(repeticoes):
                if self._stop.is_set():
                    break
                if log:
                    print(f"[play] repeticao {i+1}/{repeticoes}")

                prev_t = 0.0
                for ev in events:
                    if self._stop.is_set():
                        break

                    if self._failsafe_corner:
                        try:
                            pos = self._ms.position
                            if pos and int(pos[0]) <= 0 and int(pos[1]) <= 0:
                                print("[play] fail-safe acionado (mouse no canto 0,0). Cancelando.")
                                self._stop.set()
                                break
                        except Exception:
                            pass

                    dt = max(0.0, ev.t - prev_t) / velocidade
                    prev_t = ev.t
                    self._sleep_coop(dt)
                    if self._stop.is_set():
                        break

                    self._exec_event(ev, log=log)
        finally:
            self._stop_hotkeys()

    def _exec_event(self, ev: MacroEvent, log: bool = True) -> None:
        t = ev.type
        d = ev.data or {}
        if log:
            print(f"[play] {t} {d}")

        if t == "mouse_move":
            self._ms.position = (int(d.get("x", 0)), int(d.get("y", 0)))
            return
        if t == "click":
            x = int(d.get("x", 0))
            y = int(d.get("y", 0))
            btn = _str_to_button(self._mouse_mod, str(d.get("button", "left")))
            pressed = bool(d.get("pressed", True))
            self._ms.position = (x, y)
            if pressed:
                self._ms.press(btn)
            else:
                self._ms.release(btn)
            return
        if t in ("key_down", "key_up"):
            key_s = d.get("key", "")
            key_obj = _str_to_key(self._keyboard_mod, key_s)
            if t == "key_down":
                self._kb.press(key_obj)
            else:
                self._kb.release(key_obj)
            return


def load_macro(path: Union[str, Path]) -> List[MacroEvent]:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    raw = data.get("events", []) if isinstance(data, dict) else []
    out: List[MacroEvent] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(MacroEvent.from_dict(item))
    out.sort(key=lambda e: e.t)
    return out


def _cmd_record(args: argparse.Namespace) -> int:
    rec = MacroRecorder(record_moves=not args.no_move, move_interval_s=args.move_interval)
    print("Gravando... pressione ENTER para parar.")
    rec.start_recording()
    try:
        input()
    except KeyboardInterrupt:
        pass
    rec.stop_recording()
    out = rec.save(args.out)
    print(f"OK: salvo em {out} ({len(rec.events)} eventos)")
    return 0


def _cmd_play(args: argparse.Namespace) -> int:
    events = load_macro(args.input)
    player = MacroPlayer(failsafe_corner=not args.no_failsafe)
    player.play_macro(events, repeticoes=args.n, velocidade=args.speed, log=not args.quiet)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Gravar e reproduzir macros (mouse + teclado).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="Gravar macro")
    p_rec.add_argument("--out", required=True)
    p_rec.add_argument("--no-move", action="store_true")
    p_rec.add_argument("--move-interval", type=float, default=0.03)
    p_rec.set_defaults(fn=_cmd_record)

    p_play = sub.add_parser("play", help="Reproduzir macro")
    p_play.add_argument("--in", dest="input", required=True)
    p_play.add_argument("-n", type=int, default=1)
    p_play.add_argument("--speed", type=float, default=1.0)
    p_play.add_argument("--quiet", action="store_true")
    p_play.add_argument("--no-failsafe", action="store_true")
    p_play.set_defaults(fn=_cmd_play)

    args = parser.parse_args(argv)
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
