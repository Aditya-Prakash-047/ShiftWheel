"""Wheel geometry: the outline (circle, squircle, square, hexagon, octagon) and the slices.

Round wheels use a slice outline with constant-width gaps and corners rounded with
quadratic curves. Other outlines cut wedges out of the
outline's ring and round their corners by shrinking and re-growing the shape.

Angles follow radial.py: first slice centred at 12 o'clock, clockwise; Qt arc angles are
degrees counter-clockwise from 3 o'clock."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPainterPathStroker, QPolygonF

_CACHE: dict[tuple, list[QPainterPath]] = {}
_OUTLINES: dict[tuple, QPainterPath] = {}


def center_angle(n: int, i: int) -> float:
    """Radians, maths convention (counter-clockwise from 3 o'clock)."""
    return math.pi / 2 - 2 * math.pi * i / n


def _pt(c: QPointF, r: float, a: float) -> QPointF:
    return QPointF(c.x() + math.cos(a) * r, c.y() - math.sin(a) * r)


def outline(kind: str, c: QPointF, R: float) -> QPainterPath:
    """The wheel's outer shape, about 2R across."""
    key = (kind, round(c.x(), 2), round(c.y(), 2), round(R, 2))
    if key in _OUTLINES:
        return _OUTLINES[key]
    p = QPainterPath()
    if kind == "square":
        s = R * 0.93
        p.addRoundedRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s), R * 0.2, R * 0.2)
    elif kind == "squircle":
        pts = []
        for k in range(160):
            t = 2 * math.pi * k / 160
            ct, st = math.cos(t), math.sin(t)
            x = math.copysign(abs(ct) ** 0.5, ct) * R * 0.97
            y = math.copysign(abs(st) ** 0.5, st) * R * 0.97
            pts.append(QPointF(c.x() + x, c.y() - y))
        p.addPolygon(QPolygonF(pts))
        p.closeSubpath()
    elif kind in ("hexagon", "octagon"):
        sides = 6 if kind == "hexagon" else 8
        off = math.pi / sides if kind == "octagon" else math.pi / 2
        pts = [_pt(c, R, off + 2 * math.pi * k / sides) for k in range(sides)]
        poly = QPainterPath()
        poly.addPolygon(QPolygonF(pts))
        poly.closeSubpath()
        p = round_corners(poly, R * 0.12)
    else:
        p.addEllipse(c, R, R)
    _OUTLINES[key] = p
    return p


def round_corners(path: QPainterPath, r: float) -> QPainterPath:
    """Shrink by r, then grow back by r with round joins: convex corners get radius r."""
    if r <= 0.5:
        return path
    st = QPainterPathStroker()
    st.setWidth(2 * r)
    st.setJoinStyle(Qt.MiterJoin)
    shrunk = path.subtracted(st.createStroke(path))
    if shrunk.isEmpty():
        return path
    grow = QPainterPathStroker()
    grow.setWidth(2 * r)
    grow.setJoinStyle(Qt.RoundJoin)
    grow.setCapStyle(Qt.RoundCap)
    return shrunk.united(grow.createStroke(shrunk)).simplified()


def ring(kind: str, c: QPointF, r_in: float, r_out: float) -> QPainterPath:
    hole = QPainterPath()
    hole.addEllipse(c, r_in, r_in)
    return outline(kind, c, r_out).subtracted(hole)


def round_slice(c: QPointF, a: float, span: float, r_in: float, r_out: float, gap: float,
                corner: float) -> QPainterPath:
    """One round slice with parallel gap edges and rounded corners."""
    lo, hi = a - span / 2, a + span / 2

    def off(radius):            # angle that keeps the gap edge `gap/2` from the bisector line
        return math.asin(min(0.95, gap / 2 / max(radius, gap / 2 + 0.01))) if gap > 0 else 0.0
    d, i = lo + off(r_out), hi - off(r_out)
    ci, g = lo + off(r_in), hi - off(r_in)
    k = 1.0 if corner > 0 else 0.0
    f = min(0.15, (i - d) * 0.24) * k
    u = min(0.18, (g - ci) * 0.18) * k
    v = r_in / max(0.01, math.cos(u))
    y = v + r_in * math.tan(u)
    o = r_out - corner
    outer = QRectF(c.x() - r_out, c.y() - r_out, 2 * r_out, 2 * r_out)
    inner = QRectF(c.x() - r_in, c.y() - r_in, 2 * r_in, 2 * r_in)
    p = QPainterPath(_pt(c, y, lo + off(y)))
    p.lineTo(_pt(c, o, lo + off(o)))
    p.quadTo(_pt(c, r_out, d), _pt(c, r_out, d + f))
    p.arcTo(outer, math.degrees(d + f), math.degrees((i - f) - (d + f)))
    p.quadTo(_pt(c, r_out, i), _pt(c, o, hi - off(o)))
    p.lineTo(_pt(c, y, hi - off(y)))
    p.quadTo(_pt(c, v, hi - off(v)), _pt(c, r_in, g - u))
    p.arcTo(inner, math.degrees(g - u), -math.degrees((g - u) - (ci + u)))
    p.quadTo(_pt(c, v, lo + off(v)), _pt(c, y, lo + off(y)))
    p.closeSubpath()
    return p


def _wedge(c: QPointF, a: float, span: float, gap: float, far: float) -> QPainterPath:
    """Everything between two rays (shifted inwards by gap/2), out to `far`."""
    lo, hi = a - span / 2, a + span / 2
    na = (math.cos(lo + math.pi / 2), math.sin(lo + math.pi / 2))
    nb = (math.cos(hi - math.pi / 2), math.sin(hi - math.pi / 2))
    a0 = QPointF(c.x() + na[0] * gap / 2, c.y() - na[1] * gap / 2)
    b0 = QPointF(c.x() + nb[0] * gap / 2, c.y() - nb[1] * gap / 2)
    pts = [a0, QPointF(a0.x() + math.cos(lo) * far, a0.y() - math.sin(lo) * far)]
    steps = max(2, int(math.degrees(span) / 10))
    for k in range(1, steps):
        pts.append(_pt(c, far * 1.5, lo + span * k / steps))
    pts += [QPointF(b0.x() + math.cos(hi) * far, b0.y() - math.sin(hi) * far), b0]
    p = QPainterPath()
    p.addPolygon(QPolygonF(pts))
    p.closeSubpath()
    return p


def slices(kind: str, n: int, c: QPointF, r_in: float, r_out: float, gap: float = 0.0,
           corner: float = 0.0) -> list[QPainterPath]:
    """Slice outlines, cached (boolean path operations aren't free)."""
    key = (kind, n, round(c.x(), 2), round(c.y(), 2), round(r_in, 2), round(r_out, 2), round(gap, 2),
           round(corner, 2))
    if key in _CACHE:
        return _CACHE[key]
    if n <= 0:
        out = []
    elif n == 1:
        out = [ring(kind, c, r_in, r_out)]
    elif kind == "circle":
        span = 2 * math.pi / n
        out = [round_slice(c, center_angle(n, i), span, r_in, r_out, gap, corner) for i in range(n)]
    else:
        span = 2 * math.pi / n
        rg = ring(kind, c, r_in, r_out)
        out = []
        for i in range(n):
            part = rg.intersected(_wedge(c, center_angle(n, i), span, gap, r_out * 2))
            out.append(round_corners(part, min(corner, 18.0) * 0.6) if corner > 0 else part.simplified())
    _CACHE[key] = out
    return out


def inside(kind: str, c: QPointF, R: float, pos: QPointF) -> bool:
    return outline(kind, c, R).contains(pos)
