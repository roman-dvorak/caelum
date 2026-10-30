"""Finding a fisheye lens' geometry from an image of the sky.

Two steps, each usable on its own:

1. `detect_image_circle` — the lit disc the lens draws on the sensor: its
   centre and radius. Works on any frame (day or night) where the disc is
   brighter than the black outside it, and on discs that overflow the sensor
   at the top and bottom (the fit ignores the points cut off by the frame).
2. `fit_lens_from_stars` — refines the centre, the azimuth of north, the
   field of view and the projection from the stars in a night frame: it
   detects the star blobs, finds the north offset by trying every azimuth
   against the catalog stars that should be visible at that time and place,
   then runs a least-squares fit on the matched pairs.

The result is a `LensConfig`-shaped dict (`center_x`, `center_y`, `radius`,
`fov_deg`, `azimuth_offset_deg`, `mirror`, `projection`) plus how well it
fits, so the UI can say "27 stars matched, 0.8 px RMS" instead of just
presenting numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import cv2
import numpy as np

from caelum.derivatives.projection import _RADIAL

from .positions import star_positions

PROJECTIONS = tuple(_RADIAL)


# ---- projection, vectorised -------------------------------------------------


def _radial_fraction(projection: str, theta: np.ndarray, theta_max: float) -> np.ndarray:
    # Same functions as `derivatives.projection`, written out for arrays.
    if projection == "equisolid_fisheye":
        f = lambda t: 2.0 * np.sin(t / 2.0)  # noqa: E731
    elif projection == "stereographic_fisheye":
        f = lambda t: 2.0 * np.tan(t / 2.0)  # noqa: E731
    elif projection == "orthographic_fisheye":
        f = np.sin
    else:
        f = lambda t: t  # noqa: E731
    return f(theta) / float(f(np.float64(theta_max)))


@dataclass
class Lens:
    """The calibration being fitted. `radius` is a fraction of the shorter image side."""

    center_x: float
    center_y: float
    radius: float
    fov_deg: float = 180.0
    azimuth_offset_deg: float = 0.0
    mirror: bool = False
    projection: str = "equidistant_fisheye"

    def to_dict(self) -> dict:
        return {
            "projection": self.projection,
            "center_x": round(self.center_x, 5),
            "center_y": round(self.center_y, 5),
            "radius": round(self.radius, 5),
            "fov_deg": round(self.fov_deg, 2),
            "azimuth_offset_deg": round(self.azimuth_offset_deg % 360.0, 2),
            "mirror": self.mirror,
        }


def project_to_pixels(alt_deg: np.ndarray, az_deg: np.ndarray, lens: Lens, size: tuple[int, int]) -> np.ndarray:
    """(N, 2) pixel coordinates; NaN for directions the lens cannot see."""
    width, height = size
    theta_max = math.radians(lens.fov_deg) / 2.0
    theta = np.radians(90.0 - np.asarray(alt_deg, dtype=float))
    visible = theta <= theta_max + 1e-9
    r = lens.radius * min(width, height) * _radial_fraction(lens.projection, np.where(visible, theta, 0.0), theta_max)
    phi = np.radians(np.asarray(az_deg, dtype=float) + lens.azimuth_offset_deg)
    if lens.mirror:
        phi = -phi
    x = lens.center_x * width + r * np.sin(phi)
    y = lens.center_y * height - r * np.cos(phi)
    out = np.stack([x, y], axis=1)
    out[~visible] = np.nan
    return out


# ---- the image circle -------------------------------------------------------


@dataclass(frozen=True)
class CircleFit:
    center_x: float  # fraction of width
    center_y: float  # fraction of height
    radius: float  # fraction of the shorter side
    radius_px: float
    #: 0..1 — the share of edge points that sit on the fitted circle. Below
    #: ~0.8 the disc is not clean (vignetting, a lit horizon, no contrast).
    confidence: float
    #: The disc overflows the frame, so part of its edge could not be used.
    cropped: bool

    def to_dict(self) -> dict:
        return {
            "center_x": round(self.center_x, 5),
            "center_y": round(self.center_y, 5),
            "radius": round(self.radius, 5),
            "radius_px": round(self.radius_px, 1),
            "confidence": round(self.confidence, 3),
            "cropped": self.cropped,
        }


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        image = image.mean(axis=2)
    return image.astype(np.float32)


def _fit_circle(points: np.ndarray) -> tuple[float, float, float]:
    """Algebraic (Kasa) least-squares circle through (N, 2) points."""
    x, y = points[:, 0], points[:, 1]
    a = np.stack([x, y, np.ones_like(x)], axis=1)
    b = -(x * x + y * y)
    (da, db, dc), *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cy = -da / 2.0, -db / 2.0
    return cx, cy, math.sqrt(max(cx * cx + cy * cy - dc, 0.0))


def detect_image_circle(image: np.ndarray, max_dim: int = 640) -> CircleFit | None:
    """The centre and radius of the lit fisheye disc, or None when there is no clear one."""
    gray = to_gray(image)
    full_h, full_w = gray.shape
    scale = min(1.0, max_dim / max(full_h, full_w))
    if scale < 1.0:
        gray = cv2.resize(gray, (round(full_w * scale), round(full_h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(gray, (0, 0), 2.0)
    h, w = gray.shape

    # What "outside the disc" looks like: the darkest corner (a disc that
    # overflows the frame has bright sky in two of them, never in all four).
    p = max(4, int(min(h, w) * 0.04))
    corners = [gray[:p, :p], gray[:p, -p:], gray[-p:, :p], gray[-p:, -p:]]
    darkest = min(corners, key=lambda c: float(np.median(c)))
    background = float(np.median(darkest))
    noise = 1.4826 * float(np.median(np.abs(darkest - background)))
    floor = background + max(2.0, 4.0 * noise)
    lit = gray > floor
    if not lit.any():
        return None
    # The edge sits where the blurred disc is part-way up to its own level; a
    # threshold at the noise floor would put it where the blur has barely
    # started, i.e. a few pixels outside the real edge.
    level = background + max(0.35 * (float(np.median(gray[lit])) - background), floor - background)
    mask = (gray > level).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel), cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    points = contour.reshape(-1, 2).astype(np.float64)

    margin = 2.0
    on_frame_edge = (points[:, 0] < margin) | (points[:, 1] < margin) | (points[:, 0] > w - 1 - margin) | (
        points[:, 1] > h - 1 - margin
    )
    usable = points[~on_frame_edge]
    if len(usable) < 30:
        return None
    cropped = bool(on_frame_edge.mean() > 0.05)

    # Fit, drop what is not on the circle (trees, a lit horizon), fit again.
    cx, cy, r = _fit_circle(usable)
    for _ in range(3):
        residual = np.abs(np.hypot(usable[:, 0] - cx, usable[:, 1] - cy) - r)
        inliers = residual <= max(1.5, 0.02 * r)
        if inliers.sum() < 30:
            return None
        cx, cy, r = _fit_circle(usable[inliers])
    residual = np.abs(np.hypot(usable[:, 0] - cx, usable[:, 1] - cy) - r)
    confidence = float((residual <= max(1.5, 0.02 * r)).mean())
    if not (0.15 * min(h, w) <= r <= 1.2 * max(h, w)):
        return None

    return CircleFit(
        center_x=cx / w,
        center_y=cy / h,
        radius=r / min(h, w),
        radius_px=r / scale,
        confidence=confidence,
        cropped=cropped,
    )


# ---- stars ------------------------------------------------------------------


def detect_stars(
    image: np.ndarray,
    *,
    max_stars: int = 150,
    sigma: float = 6.0,
    max_dim: int = 1600,
    circle: tuple[float, float, float] | None = None,
) -> np.ndarray:
    """(N, 3) array of (x_px, y_px, flux) in full-resolution pixels, brightest
    first. `circle` = (cx_px, cy_px, r_px) restricts the search to the inside
    of the lens disc (stars of the horizon ring are the most distorted)."""
    gray = to_gray(image)
    full_h, full_w = gray.shape
    scale = min(1.0, max_dim / max(full_h, full_w))
    if scale < 1.0:
        gray = cv2.resize(gray, (round(full_w * scale), round(full_h * scale)), interpolation=cv2.INTER_AREA)
    smooth = cv2.GaussianBlur(gray, (0, 0), 1.0)
    background = cv2.GaussianBlur(gray, (0, 0), 12.0)
    residual = smooth - background
    if circle is not None:
        valid = np.zeros(gray.shape, np.uint8)
        cv2.circle(valid, (round(circle[0] * scale), round(circle[1] * scale)), round(circle[2] * scale * 0.97), 1, -1)
        values = residual[valid > 0]
    else:
        valid = None
        values = residual.ravel()
    if values.size == 0:
        return np.zeros((0, 3))
    noise = 1.4826 * float(np.median(np.abs(values - np.median(values))))
    mask = (residual > max(sigma * noise, 1e-3)).astype(np.uint8)
    if valid is not None:
        mask &= valid
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    stars = []
    for i in range(1, count):
        area = stats[i, cv2.CC_STAT_AREA]
        if not 2 <= area <= 400:
            continue
        x0, y0, bw, bh = (
            stats[i, k] for k in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT)
        )
        weights = np.where(labels[y0 : y0 + bh, x0 : x0 + bw] == i, residual[y0 : y0 + bh, x0 : x0 + bw], 0.0)
        flux = float(weights.sum())
        if flux <= 0 or max(bw, bh) > 4 * min(bw, bh) + 2:
            continue  # a streak or an edge, not a star
        ys, xs = np.mgrid[y0 : y0 + bh, x0 : x0 + bw]
        stars.append(((xs * weights).sum() / flux + 0.5, (ys * weights).sum() / flux + 0.5, flux))
    if not stars:
        return np.zeros((0, 3))
    array = np.array(sorted(stars, key=lambda s: -s[2])[:max_stars])
    array[:, 0] /= scale
    array[:, 1] /= scale
    return array


# ---- matching and fitting ---------------------------------------------------


@dataclass
class LensFit:
    lens: Lens
    rms_px: float
    matched: int
    candidates: int  # catalog stars that should have been visible
    detected: int
    #: One entry per matched star: its pixel position and name.
    matches: list[dict] = field(default_factory=list)
    #: RMS of the other projections tried, so the UI can show the comparison.
    by_projection: dict[str, float] = field(default_factory=dict)

    @property
    def confidence(self) -> float:
        """0..1 — mostly "did enough stars line up, and tightly"."""
        if self.matched < 6:
            return 0.0
        coverage = min(1.0, self.matched / 25.0)
        tightness = 1.0 / (1.0 + self.rms_px / 3.0)
        return round(coverage * tightness, 3)

    def to_dict(self) -> dict:
        return {
            "lens": self.lens.to_dict(),
            "rms_px": round(self.rms_px, 2),
            "matched": self.matched,
            "candidates": self.candidates,
            "detected": self.detected,
            "confidence": self.confidence,
            "matches": self.matches,
            "by_projection": {k: round(v, 2) for k, v in self.by_projection.items()},
        }


def _match(predicted: np.ndarray, detected_xy: np.ndarray, tolerance: float) -> list[tuple[int, int, float]]:
    """Greedy one-to-one nearest neighbours: (catalog index, detected index, distance)."""
    ok = ~np.isnan(predicted[:, 0])
    if not ok.any() or len(detected_xy) == 0:
        return []
    idx = np.flatnonzero(ok)
    d = np.hypot(predicted[idx, None, 0] - detected_xy[None, :, 0], predicted[idx, None, 1] - detected_xy[None, :, 1])
    pairs = [(d[i, j], idx[i], j) for i, j in zip(*np.nonzero(d <= tolerance), strict=True)]
    pairs.sort()
    used_c, used_d, out = set(), set(), []
    for dist, c, j in pairs:
        if c in used_c or j in used_d:
            continue
        used_c.add(c)
        used_d.add(j)
        out.append((int(c), int(j), float(dist)))
    return out


def _residuals(params: np.ndarray, free: list[str], lens: Lens, alt: np.ndarray, az: np.ndarray,
               pairs: list[tuple[int, int, float]], detected_xy: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    trial = Lens(**{**lens.__dict__, **dict(zip(free, params, strict=True))})
    predicted = project_to_pixels(alt, az, trial, size)
    cat = np.array([p[0] for p in pairs])
    det = np.array([p[1] for p in pairs])
    diff = predicted[cat] - detected_xy[det]
    diff = np.nan_to_num(diff, nan=1e3)
    return diff.ravel()


def _levenberg_marquardt(fun, x0: np.ndarray, iterations: int = 30) -> np.ndarray:
    x = x0.astype(float).copy()
    lam = 1e-2
    r = fun(x)
    cost = float(r @ r)
    for _ in range(iterations):
        jac = np.empty((r.size, x.size))
        for k in range(x.size):
            step = 1e-6 * max(1.0, abs(x[k]))
            xp = x.copy()
            xp[k] += step
            jac[:, k] = (fun(xp) - r) / step
        a = jac.T @ jac
        g = jac.T @ r
        improved = False
        for _ in range(8):
            try:
                delta = np.linalg.solve(a + lam * np.diag(np.diag(a) + 1e-12), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            r_new = fun(x + delta)
            cost_new = float(r_new @ r_new)
            if cost_new < cost:
                x, r, cost = x + delta, r_new, cost_new
                lam = max(lam / 3.0, 1e-9)
                improved = True
                break
            lam *= 4
        if not improved or float(np.abs(delta).max()) < 1e-9:
            break
    return x


def fit_lens_from_stars(
    stars_px: np.ndarray,
    size: tuple[int, int],
    when: datetime,
    lat_deg: float,
    lon_deg: float,
    initial: Lens,
    *,
    fit_fov: bool = True,
    projections: tuple[str, ...] | None = None,
    max_mag: float = 4.5,
    min_alt_deg: float = 10.0,
) -> LensFit | None:
    """Fit the lens to detected star positions (`detect_stars`' output).

    `initial` supplies the centre and radius (from `detect_image_circle` or
    the configured lens); the azimuth offset and the mirroring are searched
    for, not assumed. With `fit_fov` the field of view is solved for with the
    radius held fixed — the radius of the disc is a measurement, the field of
    view is what the stars say it must be. Returns None when too few stars
    line up to say anything."""
    detected_xy = stars_px[:, :2]
    if len(detected_xy) < 6:
        return None
    catalog = star_positions(when, lat_deg, lon_deg, max_mag=max_mag)
    visible = np.flatnonzero(catalog.alt_deg >= min_alt_deg)
    if len(visible) < 6:
        return None
    alt, az = catalog.alt_deg[visible], catalog.az_deg[visible]
    names = [catalog.names[i] for i in visible]
    radius_px = initial.radius * min(size)

    # North offset: try every azimuth (and both handednesses) and count how
    # many catalog stars land on a detected one.
    best_score, best_start = -1, None
    for mirror in (False, True):
        for offset in np.arange(0.0, 360.0, 1.0):
            trial = Lens(**{**initial.__dict__, "azimuth_offset_deg": float(offset), "mirror": mirror})
            predicted = project_to_pixels(alt, az, trial, size)
            score = len(_match(predicted, detected_xy, 0.03 * radius_px))
            if score > best_score:
                best_score, best_start = score, trial
    if best_start is None or best_score < 5:
        return None

    results: list[LensFit] = []
    for projection in projections or PROJECTIONS:
        lens = Lens(**{**best_start.__dict__, "projection": projection})
        free = ["center_x", "center_y", "azimuth_offset_deg"] + (["fov_deg"] if fit_fov else ["radius"])
        pairs: list[tuple[int, int, float]] = []
        for tolerance in (0.03, 0.015, 0.008, 0.004):
            predicted = project_to_pixels(alt, az, lens, size)
            pairs = _match(predicted, detected_xy, tolerance * radius_px)
            if len(pairs) < 5:
                break
            x0 = np.array([getattr(lens, k) for k in free])
            solved = _levenberg_marquardt(
                lambda x, free=free, lens=lens, pairs=pairs: _residuals(
                    x, free, lens, alt, az, pairs, detected_xy, size
                ),
                x0,
            )
            lens = Lens(**{**lens.__dict__, **dict(zip(free, solved, strict=True))})
        predicted = project_to_pixels(alt, az, lens, size)
        pairs = _match(predicted, detected_xy, 0.008 * radius_px)
        if len(pairs) < 5:
            continue
        rms = math.sqrt(float(np.mean([d * d for _, _, d in pairs])))
        matches = [
            {"name": names[c], "x": round(float(detected_xy[j, 0]), 1), "y": round(float(detected_xy[j, 1]), 1),
             "error_px": round(d, 2)}
            for c, j, d in sorted(pairs, key=lambda p: p[2])
        ]
        results.append(LensFit(lens, rms, len(pairs), len(visible), len(detected_xy), matches))

    if not results:
        return None
    # Fewer matches with a tiny RMS is not better than many with a small one:
    # rank by RMS, but only among fits that kept most of the stars.
    most = max(r.matched for r in results)
    solid = [r for r in results if r.matched >= 0.8 * most]
    best = min(solid, key=lambda r: r.rms_px)
    best.by_projection = {r.lens.projection: r.rms_px for r in results}
    return best
