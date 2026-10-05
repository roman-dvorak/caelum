#!/usr/bin/env python3
"""Plot the exposure loop over time, all in EV: exposure*gain, brightness
vs target, and the regulator's error and P/I terms.

Dependency-free (standard library only) — writes one self-contained HTML
file with SVG charts, to open in any browser:

    .venv/bin/python scripts/plot_exposure.py --hours 8 -o exposure.html
    .venv/bin/python scripts/plot_exposure.py --since 2026-10-02T22:00 --until 2026-10-03T04:00

Data sources, per capture:
- thumbnail sidecars (`thumbnails/YYYY/MM/DD/*.json`): exposure, gain, and —
  for frames recorded since it was added — `exposure_control`, the
  regulator's actual cycle (brightness, error, P/I terms, …);
- for older frames, the raw DNG's XMP for the brightness (median and target,
  ADU), from which only the error can be derived — no P/I.

Brightness EV is relative to full scale (0 EV = 255 ADU).
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Point:
    t: datetime
    exposure_s: float
    gain: float
    period: str | None = None
    measured_ev: float | None = None
    target_ev: float | None = None
    error_ev: float | None = None
    p_ev: float | None = None
    i_ev: float | None = None
    output_ev: float | None = None
    legacy: bool = False
    limited: str | None = None


# ---- reading ----------------------------------------------------------------


def _dng_xmp(path: Path) -> dict[str, str]:
    """caelum:* fields from a DNG's XMP tag — reads only IFD0 + the packet."""
    try:
        with path.open("rb") as f:
            head = f.read(8)
            if head[:4] != b"II*\x00":
                return {}
            f.seek(struct.unpack_from("<L", head, 4)[0])
            (count,) = struct.unpack("<H", f.read(2))
            entries = f.read(12 * count)
            for i in range(count):
                tag, _typ, n, value = struct.unpack_from("<HHLL", entries, 12 * i)
                if tag == 700:
                    f.seek(value)
                    xmp = f.read(n).decode("utf-8", "replace")
                    return dict(re.findall(r'caelum:(\w+)="([^"]*)"', xmp))
    except OSError:
        pass
    return {}


def _stem_time(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem.split("_", 1)[0], "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _days(since: datetime, until: datetime):
    day = since.date()
    while day <= until.date():
        yield day
        day += timedelta(days=1)


def load_points(data_dir: Path, since: datetime, until: datetime) -> list[Point]:
    points: list[Point] = []
    for day in _days(since, until):
        rel = Path(f"{day:%Y}/{day:%m}/{day:%d}")
        for sidecar in sorted((data_dir / "thumbnails" / rel).glob("*.json")):
            t = _stem_time(sidecar)
            if t is None or not (since <= t <= until):
                continue
            try:
                meta = json.loads(sidecar.read_text())
            except (OSError, ValueError):
                continue
            point = Point(
                t=datetime.fromisoformat(meta["captured_at"]),
                exposure_s=meta["exposure_us"] / 1e6,
                gain=float(meta["analogue_gain"]),
                period=(meta.get("sky_state") or {}).get("period"),
            )
            control = meta.get("exposure_control") or {}
            if "measured_ev" in control:
                point.measured_ev = control.get("measured_ev")
                point.target_ev = control.get("target_ev")
                point.error_ev = control.get("error_ev")
                point.p_ev = control.get("p_term_ev")
                point.i_ev = control.get("i_term_ev")
                point.output_ev = control.get("output_ev")
                point.limited = control.get("limited")
            else:
                xmp = _dng_xmp(data_dir / "raw" / rel / f"{sidecar.stem}.dng")
                if "brightness_median" in xmp and "brightness_target" in xmp:
                    point.measured_ev = _adu_ev(float(xmp["brightness_median"]))
                    point.target_ev = _adu_ev(float(xmp["brightness_target"]))
                    point.error_ev = point.target_ev - point.measured_ev
                    point.legacy = True
            points.append(point)
    points.sort(key=lambda p: p.t)
    return points


def _adu_ev(adu: float) -> float:
    return math.log2(max(adu, 0.5) / 255.0)


# ---- SVG --------------------------------------------------------------------

W, H, ML, MR, MT, MB = 1200, 250, 70, 70, 26, 34
COLORS = {
    "exposure": "#e8a13a",
    "gain": "#6bb3c4",
    "median": "#f3ede1",
    "target": "#7cad76",
    "error": "#de6a56",
    "p": "#6bb3c4",
    "i": "#c792ea",
}


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.ceil(lo / step) * step
    return [start + k * step for k in range(int((hi - start) / step) + 1)]


class Panel:
    def __init__(self, title: str, t0: datetime, t1: datetime, tz: ZoneInfo) -> None:
        self.title, self.t0, self.t1, self.tz = title, t0, t1, tz
        self.parts: list[str] = []
        self.legend: list[tuple[str, str, bool]] = []

    def x(self, t: datetime) -> float:
        span = (self.t1 - self.t0).total_seconds() or 1
        return ML + (W - ML - MR) * (t - self.t0).total_seconds() / span

    @staticmethod
    def _scale(lo: float, hi: float):
        if hi <= lo:
            lo, hi = lo - 1, hi + 1
        return lambda v: MT + (H - MT - MB) * (1 - (v - lo) / (hi - lo))

    def axis(self, lo: float, hi: float, side: str, label: str, fmt, ticks=None) -> None:
        y = self._scale(lo, hi)
        x_line = ML if side == "left" else W - MR
        anchor, dx = ("end", -6) if side == "left" else ("start", 6)
        for v in ticks if ticks is not None else _nice_ticks(lo, hi):
            if not lo <= v <= hi:
                continue
            if side == "left":
                self.parts.append(f'<line x1="{ML}" x2="{W - MR}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>')
            self.parts.append(
                f'<text x="{x_line + dx}" y="{y(v) + 4:.1f}" text-anchor="{anchor}" class="tick">{html.escape(fmt(v))}</text>'
            )
        lx = 14 if side == "left" else W - 14
        self.parts.append(
            f'<text x="{lx}" y="{H / 2}" transform="rotate(-90 {lx} {H / 2})" text-anchor="middle" class="axis">'
            f"{html.escape(label)}</text>"
        )

    def series(self, pts, lo, hi, name, color, *, dashed=False, step=False, dots=False) -> None:
        y = self._scale(lo, hi)
        segments, current, prev_t = [], [], None
        for t, v in pts:
            if v is None or not math.isfinite(v):
                continue
            if prev_t is not None and (t - prev_t) > timedelta(minutes=10) and current:
                segments.append(current)
                current = []
            current.append((self.x(t), y(min(max(v, lo), hi))))
            prev_t = t
        if current:
            segments.append(current)
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        for seg in segments:
            if step and len(seg) > 1:
                d = [f"M{seg[0][0]:.1f},{seg[0][1]:.1f}"]
                for (x0, _), (x1, y1) in zip(seg, seg[1:], strict=False):
                    d.append(f"H{x1:.1f}V{y1:.1f}")
                path = "".join(d)
            else:
                path = "M" + "L".join(f"{a:.1f},{b:.1f}" for a, b in seg)
            self.parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6"{dash}/>')
            if dots:
                self.parts.extend(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="1.8" fill="{color}"/>' for a, b in seg)
        self.legend.append((name, color, dashed))

    def zero_line(self, lo: float, hi: float) -> None:
        if lo < 0 < hi:
            y0 = self._scale(lo, hi)(0)
            self.parts.append(f'<line x1="{ML}" x2="{W - MR}" y1="{y0:.1f}" y2="{y0:.1f}" class="zero"/>')

    def svg(self) -> str:
        span_h = (self.t1 - self.t0).total_seconds() / 3600
        step = next(s for s in (0.25, 0.5, 1, 2, 3, 6, 12, 24) if span_h / s <= 12)
        t = self.t0.astimezone(self.tz).replace(minute=0, second=0, microsecond=0)
        xticks = []
        while t <= self.t1:
            if t >= self.t0:
                xticks.append(
                    f'<line x1="{self.x(t):.1f}" x2="{self.x(t):.1f}" y1="{MT}" y2="{H - MB}" class="grid"/>'
                    f'<text x="{self.x(t):.1f}" y="{H - MB + 16}" text-anchor="middle" class="tick">{t:%H:%M}</text>'
                )
            t += timedelta(hours=step)
        legend, lx = [], ML
        for name, color, dashed in self.legend:
            dash = ' stroke-dasharray="5 4"' if dashed else ""
            legend.append(
                f'<line x1="{lx}" x2="{lx + 22}" y1="12" y2="12" stroke="{color}" stroke-width="2"{dash}/>'
                f'<text x="{lx + 28}" y="16" class="legend">{html.escape(name)}</text>'
            )
            lx += 40 + 7.2 * len(name)
        return (
            f'<figure><figcaption>{html.escape(self.title)}</figcaption>'
            f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(self.title)}">'
            f'<rect x="{ML}" y="{MT}" width="{W - ML - MR}" height="{H - MT - MB}" class="plot"/>'
            + "".join(xticks)
            + "".join(self.parts)
            + "".join(legend)
            + "</svg></figure>"
        )


def _fmt_seconds(log2s: float) -> str:
    s = 2**log2s
    return f"{s:.3g} s" if s >= 1 else f"{s * 1000:.3g} ms"


def render(points: list[Point], tz: ZoneInfo, title: str) -> str:
    t0, t1 = points[0].t, points[-1].t
    if t1 == t0:
        t1 = t0 + timedelta(minutes=1)

    # 1) exposure*gain in EV: exposure, gain and their sum
    exp_panel = Panel("Expozice a gain (EV)", t0, t1, tz)
    ev_t = [math.log2(p.exposure_s) for p in points]
    ev_g = [math.log2(max(p.gain, 1e-6)) for p in points]
    totals = [a + b for a, b in zip(ev_t, ev_g, strict=True)]
    lo = math.floor(min(min(ev_t), min(ev_g), min(totals))) - 0.5
    hi = math.ceil(max(max(ev_t), max(ev_g), max(totals))) + 0.5
    exp_panel.axis(lo, hi, "left", "EV", lambda v: f"{v:+.0f}", ticks=list(range(math.ceil(lo), math.floor(hi) + 1)))
    exp_panel.axis(lo, hi, "right", "expozice", _fmt_seconds, ticks=list(range(math.ceil(lo), math.floor(hi) + 1)))
    exp_panel.series(list(zip([p.t for p in points], totals, strict=True)), lo, hi, "expozice+gain", COLORS["median"], step=True)
    exp_panel.series(list(zip([p.t for p in points], ev_t, strict=True)), lo, hi, "expozice", COLORS["exposure"], step=True)
    exp_panel.series(list(zip([p.t for p in points], ev_g, strict=True)), lo, hi, "gain", COLORS["gain"], step=True,
                     dashed=True)

    # 2) brightness vs target (EV below full scale)
    bright = Panel("Jas (medián kruhu) vs. setpoint, EV pod plnou škálou", t0, t1, tz)
    vals = [v for p in points for v in (p.measured_ev, p.target_ev) if v is not None]
    if vals:
        blo, bhi = min(-3.0, math.floor(min(vals))), 0.0
        bright.axis(blo, bhi, "left", "EV", lambda v: f"{v:+.1f}")
        bright.series([(p.t, p.measured_ev) for p in points], blo, bhi, "jas", COLORS["median"], dots=True)
        bright.series([(p.t, p.target_ev) for p in points], blo, bhi, "setpoint", COLORS["target"], step=True,
                      dashed=True)

    # 3) error, P, I (EV)
    any_legacy = any(p.legacy for p in points)
    reg = Panel(
        "Regulátor: chyba, P a I (EV)" + (" — u starších snímků jen chyba" if any_legacy else ""), t0, t1, tz
    )
    evs = [v for p in points for v in (p.error_ev, p.p_ev, p.i_ev) if v is not None]
    if evs:
        m = max(1.0, max(abs(v) for v in evs)) * 1.1
        reg.axis(-m, m, "left", "EV", lambda v: f"{v:+.1f}")
        reg.zero_line(-m, m)
        reg.series([(p.t, p.error_ev) for p in points], -m, m, "chyba", COLORS["error"], dots=True)
        reg.series([(p.t, p.p_ev) for p in points], -m, m, "P", COLORS["p"])
        reg.series([(p.t, p.i_ev) for p in points], -m, m, "I", COLORS["i"])

    span = f"{t0.astimezone(tz):%Y-%m-%d %H:%M} – {t1.astimezone(tz):%Y-%m-%d %H:%M} ({tz.key})"
    return f"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{margin:0;padding:16px;background:#0b0a08;color:#f3ede1;font:14px system-ui,sans-serif}}
h1{{font-size:16px;margin:0 0 4px}} p{{color:#ab9d89;margin:0 0 16px}}
figure{{margin:0 0 18px;background:#16130f;border:1px solid #2f2a20;padding:8px}}
figcaption{{color:#ab9d89;font-size:12px;text-transform:uppercase;letter-spacing:.12em;margin:2px 0 4px 4px}}
svg{{width:100%;height:auto;display:block}}
.plot{{fill:none;stroke:#2f2a20}} .grid{{stroke:#211d17}} .zero{{stroke:#6e6353;stroke-dasharray:2 3}}
.tick{{fill:#6e6353;font-size:11px}} .axis{{fill:#ab9d89;font-size:12px}} .legend{{fill:#ab9d89;font-size:12px}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p>{html.escape(span)} · {len(points)} snímků</p>
{exp_panel.svg()}
{bright.svg()}
{reg.svg()}
</body></html>
"""


def _parse_time(value: str, tz: ZoneInfo) -> datetime:
    t = datetime.fromisoformat(value)
    return (t if t.tzinfo else t.replace(tzinfo=tz)).astimezone(UTC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "config.json")
    parser.add_argument("--hours", type=float, default=12.0, help="last N hours (default 12); ignored with --since")
    parser.add_argument("--since", help="start, ISO time (local timezone unless given)")
    parser.add_argument("--until", help="end, ISO time (default now)")
    parser.add_argument("-o", "--out", type=Path, default=Path("exposure.html"))
    args = parser.parse_args()

    try:
        config = json.loads(args.config.read_text())
    except (OSError, ValueError):
        config = {}
    tz = ZoneInfo((config.get("location") or {}).get("timezone", "UTC"))
    until = _parse_time(args.until, tz) if args.until else datetime.now(UTC)
    since = _parse_time(args.since, tz) if args.since else until - timedelta(hours=args.hours)

    points = load_points(args.data_dir, since, until)
    if not points:
        print(f"No captures between {since:%Y-%m-%d %H:%M} and {until:%Y-%m-%d %H:%M} UTC", file=sys.stderr)
        return 1
    args.out.write_text(render(points, tz, "caelum — regulace expozice"))
    print(f"{args.out} ({len(points)} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
