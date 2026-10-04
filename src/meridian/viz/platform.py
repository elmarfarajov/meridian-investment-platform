"""Charts for the platform: how it is built, how it is guarded, how it behaves under use, and how it grew.

The questions an engineering reviewer, a security officer and an operator ask,
one figure each - drawn from the code itself (the import graph, the OpenAPI
document, the role matrix), from a measured working day on the real modules,
and from the git history.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

from .accounting import _margins
from .style import PALETTE, caption, new_figure, style_axes, title_block

INK, MUTED, GRID, BAND = PALETTE["ink"], PALETTE["muted"], PALETTE["grid"], PALETTE["band"]
NAVY, TEAL, VIOLET, SKY, SLATE = PALETTE["navy"], PALETTE["teal"], PALETTE["violet"], PALETTE["sky"], PALETTE["slate"]
GAIN, LOSS, AMBER = PALETTE["gain"], PALETTE["loss"], PALETTE["accent"]
GOLD = "#D9A21B"
METHOD_COLOURS = {"GET": SKY, "POST": TEAL, "PUT": GOLD, "DELETE": LOSS}
STATUS_COLOURS = {2: GAIN, 4: GOLD, 5: LOSS}
DARK = {"bg": "#0F1623", "panel": "#161F30", "edge": "#24324A", "text": "#E6ECF5", "muted": "#8A9BB5"}


def _box(
    axis: Axes,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    lines: Sequence[str] = (),
    *,
    colour: str = NAVY,
    fill: str | None = None,
    text: str = "white",
    size: float = 9.0,
) -> None:
    axis.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.004,rounding_size=0.012",
            facecolor=fill or colour,
            edgecolor=colour,
            linewidth=1.2,
        )
    )
    axis.text(x + w / 2, y + h - 0.022, title, ha="center", va="top", fontsize=size, weight="bold", color=text)
    for index, line in enumerate(lines):
        axis.text(
            x + w / 2,
            y + h - 0.052 - index * 0.026,
            line,
            ha="center",
            va="top",
            fontsize=size - 1.6,
            color=text if fill is None else INK,
        )


def _arrow(
    axis: Axes,
    start: tuple[float, float],
    end: tuple[float, float],
    colour: str = SLATE,
    width: float = 1.4,
    style: str = "-|>",
    curve: float = 0.0,
) -> None:
    axis.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=12,
            color=colour,
            linewidth=width,
            connectionstyle=f"arc3,rad={curve}",
        )
    )


def _canvas(figure: Figure, rect: tuple[float, float, float, float] = (0.01, 0.03, 0.98, 0.84)) -> Axes:
    axis = figure.add_axes(rect)
    axis.set_xlim(0, 1)
    axis.set_ylim(0, 1)
    axis.axis("off")
    return axis


# ---------------------------------------------------------------------------- 1. the architecture
def plot_architecture(modules: Sequence[tuple[str, str, str]], counts: Mapping[str, str]) -> Figure:
    """The platform in layers: who uses it, the API and its controls, the nine modules, storage and operations.

    ``modules`` are (name, day label, one-line description).
    """
    figure = new_figure(16.0, 10.4)
    axis = _canvas(figure, (0.01, 0.02, 0.98, 0.86))
    # users
    users = [
        ("Client", "reads reports"),
        ("Analyst", "reads analytics"),
        ("Portfolio manager", "proposes, orders"),
        ("Trader", "orders, costs"),
        ("Compliance", "approves, audits"),
        ("Operator", "CLI, Grafana"),
    ]
    for index, (name, role) in enumerate(users):
        _box(axis, 0.02 + index * 0.163, 0.9, 0.145, 0.085, name, [role], colour=SLATE)
    # the API band
    axis.add_patch(
        FancyBboxPatch(
            (0.02, 0.67),
            0.96,
            0.19,
            boxstyle="round,pad=0.004,rounding_size=0.015",
            facecolor="#EEF3FA",
            edgecolor=NAVY,
            linewidth=1.6,
        )
    )
    axis.text(0.035, 0.845, "Web platform  ·  FastAPI  ·  OpenAPI 3.1", fontsize=10.5, weight="bold", color=NAVY)
    controls = [
        ("Request id", "traced end to end"),
        ("Authentication", "JWT, PBKDF2 passwords"),
        ("Authorisation", "roles, entitlements"),
        ("Rate limit", "token bucket"),
        ("Idempotency", "safe retries"),
        ("Handler", "asks, never computes"),
        ("Audit + metrics", "hash chain, Prometheus"),
    ]
    for index, (name, detail) in enumerate(controls):
        x = 0.035 + index * 0.134
        _box(axis, x, 0.69, 0.122, 0.12, name, [detail], colour=NAVY if name != "Handler" else TEAL)
        if index < len(controls) - 1:
            _arrow(axis, (x + 0.122, 0.75), (x + 0.134, 0.75), colour=NAVY)
    for index in range(6):
        _arrow(axis, (0.0925 + index * 0.163, 0.9), (0.0925 + index * 0.163, 0.865), colour=SLATE)
    # the modules
    axis.text(
        0.035,
        0.625,
        "Domain modules - the same objects the CLI, the charts and the client report use",
        fontsize=10,
        weight="bold",
        color=INK,
    )
    colours = (SKY, SKY, VIOLET, VIOLET, TEAL, TEAL, NAVY, NAVY, SLATE)
    for index, (name, day, description) in enumerate(modules):
        row, column = divmod(index, 5)
        x = 0.035 + column * 0.188
        y = 0.48 - row * 0.14
        _box(axis, x, y, 0.172, 0.12, name, [day, description], colour=colours[index % len(colours)])
    _arrow(axis, (0.5, 0.69), (0.5, 0.635), colour=TEAL, width=2.0)
    # storage and operations
    _box(
        axis,
        0.035,
        0.05,
        0.29,
        0.15,
        "PostgreSQL 16  ·  SQLite",
        [counts.get("tables", ""), "Alembic migrations 0001-0009"],
        colour=INK,
    )
    _box(axis, 0.355, 0.05, 0.29, 0.15, "Docker Compose", ["api, db, migrate,", "prometheus, grafana"], colour=SLATE)
    _box(
        axis,
        0.675,
        0.05,
        0.29,
        0.15,
        "Prometheus  ·  Grafana",
        ["request rate, latency, refusals", "audit records, errors"],
        colour=VIOLET,
    )
    axis.text(0.035, 0.225, "Storage and operations", fontsize=10, weight="bold", color=INK)
    _arrow(axis, (0.18, 0.34), (0.18, 0.2), colour=INK, width=1.8)
    axis.text(0.19, 0.265, "SQLAlchemy 2.0, unit of work", fontsize=8, color=INK)
    _arrow(axis, (0.982, 0.69), (0.982, 0.2), colour=VIOLET, width=1.6)
    axis.text(0.975, 0.45, "/metrics", fontsize=8, color=VIOLET, rotation=90, ha="right", va="center")
    title_block(
        figure,
        "Meridian Investment Platform: the architecture",
        "Six kinds of user, one API that authenticates, authorises, rate-limits, deduplicates and audits every "
        "request, "
        "and nine modules built day by day underneath. " + counts.get("summary", ""),
    )
    return figure


# ---------------------------------------------------------------------------- 2. the request pipeline
def plot_pipeline(stages: Sequence[tuple[str, int, str]], total: int) -> Figure:
    """What happened to a working day's requests at each layer: (layer, requests stopped there, why)."""
    figure = new_figure(16.0, 7.6)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.05, right=0.97))
    axis = figure.add_subplot(grid[0])
    remaining = total
    positions = np.arange(len(stages) + 1)
    heights = [total]
    for _, stopped, _ in stages:
        remaining -= stopped
        heights.append(remaining)
    axis.bar(positions, heights, color=[NAVY] + [TEAL] * len(stages), width=0.62, alpha=0.9)
    for index, (_, stopped, why) in enumerate(stages, start=1):
        if stopped:
            axis.bar(index, stopped, bottom=heights[index], color=GOLD if "idempot" not in why else SKY, width=0.62)
            axis.text(
                index,
                heights[index] + stopped + total * 0.012,
                f"{stopped:,}\n{why}",
                ha="center",
                fontsize=8.2,
                color=GOLD if "idempot" not in why else SKY,
                weight="bold",
            )
    for index, height in enumerate(heights):
        axis.text(index, height / 2, f"{height:,}", ha="center", va="center", color="white", fontsize=10, weight="bold")
    axis.set_xticks(positions, labels=["requests", *[stage[0] for stage in stages]], fontsize=9)
    axis.set_ylim(0, total * 1.22)
    style_axes(
        axis,
        title="Requests remaining after each layer (amber: stopped there; blue: answered from the idempotency store)",
        grid="y",
    )
    title_block(
        figure,
        "Seven layers between a request and the data",
        f"A working day on the platform: {total:,} requests from seven people, one of them an intruder. Each layer "
        "stops what it should - and every request, stopped or not, is written to the audit chain.",
    )
    caption(figure, "Measured by driving the API over HTTP against the real modules (meridian.devtools.workload).")
    return figure


# ---------------------------------------------------------------------------- 3. the role matrix
def plot_rbac(
    roles: Sequence[str], permissions: Sequence[str], matrix: Sequence[Sequence[bool]], users: Mapping[str, str]
) -> Figure:
    figure = new_figure(16.0, 7.8)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.25, left=0.16, right=0.97))
    axis = figure.add_subplot(grid[0])
    data = np.array(matrix, dtype=float)
    colours = np.where(data > 0, 1.0, 0.0)
    from matplotlib.colors import ListedColormap

    axis.imshow(colours, cmap=ListedColormap([BAND, TEAL]), aspect="auto", vmin=0, vmax=1)
    for row in range(data.shape[0]):
        for column in range(data.shape[1]):
            axis.text(
                column,
                row,
                "✓" if data[row, column] else "·",
                ha="center",
                va="center",
                color="white" if data[row, column] else MUTED,
                fontsize=13 if data[row, column] else 10,
                weight="bold",
            )
    axis.set_xticks(range(len(permissions)), labels=permissions, rotation=35, ha="right", fontsize=9)
    axis.set_yticks(
        range(len(roles)), labels=[f"{role.replace('_', ' ')}\n({users.get(role, '')})" for role in roles], fontsize=9
    )
    axis.set_xticks(np.arange(-0.5, len(permissions)), minor=True)
    axis.set_yticks(np.arange(-0.5, len(roles)), minor=True)
    axis.grid(which="minor", color="white", linewidth=2)
    axis.grid(which="major", visible=False)
    axis.tick_params(which="minor", length=0)
    for column, permission in enumerate(permissions):
        if permission in ("orders:create", "orders:approve"):
            axis.add_patch(
                FancyBboxPatch(
                    (column - 0.48, -0.48),
                    0.96,
                    len(roles) - 0.04,
                    boxstyle="round,pad=0,rounding_size=0.1",
                    fill=False,
                    edgecolor=AMBER,
                    linewidth=2,
                )
            )
    axis.set_title(
        "Permissions by role (the amber columns never meet in one role: whoever enters an order cannot approve it)",
        loc="left",
    )
    title_block(
        figure,
        "Role-based access control, with separation of duties",
        "Endpoints check permissions, never roles; a role is a bundle of permissions. Entitlements narrow them "
        "further: "
        "a client reads only the portfolios on her own record, and sees any other as if it did not exist.",
    )
    caption(
        figure,
        "meridian.api.security.ROLES. The administrator manages users and reads the audit log - and cannot see client "
        "data or trade.",
    )
    return figure


# ---------------------------------------------------------------------------- 4. the API surface
def plot_api_surface(rows: Sequence[tuple[str, str, str, str, str]]) -> Figure:
    """Every endpoint: (tag, method, path, permission, summary), grouped by tag."""
    figure = new_figure(16.0, 1.6 + 0.43 * len(rows))
    axis = _canvas(figure, (0.01, 0.02, 0.98, 0.86))
    step = 0.97 / (len(rows) + len({row[0] for row in rows}) * 1.5 + 0.5)
    y = 0.98
    previous = None
    for tag, method, path, permission, summary in rows:
        if tag != previous:
            y -= step * 0.6
            axis.text(0.0, y, tag.upper(), fontsize=9, weight="bold", color=MUTED)
            y -= step * 0.9
            previous = tag
        axis.add_patch(
            FancyBboxPatch(
                (0.0, y - step * 0.32),
                0.055,
                step * 0.64,
                boxstyle="round,pad=0,rounding_size=0.006",
                facecolor=METHOD_COLOURS.get(method, SLATE),
                edgecolor="none",
            )
        )
        axis.text(0.0275, y, method, ha="center", va="center", fontsize=8.2, weight="bold", color="white")
        axis.text(0.065, y, path, va="center", fontsize=9.2, family="monospace", color=INK)
        colour = GAIN if permission == "public" else (SKY if permission == "authenticated" else VIOLET)
        axis.add_patch(
            FancyBboxPatch(
                (0.43, y - step * 0.3),
                0.15,
                step * 0.6,
                boxstyle="round,pad=0,rounding_size=0.006",
                facecolor=colour,
                edgecolor="none",
                alpha=0.18,
            )
        )
        axis.text(0.505, y, permission, ha="center", va="center", fontsize=8.4, color=colour, weight="bold")
        axis.text(0.6, y, summary, va="center", fontsize=8.6, color=MUTED)
        y -= step
    title_block(
        figure,
        f"The API: {len(rows)} endpoints, each with the permission it requires",
        "Read from the service's own OpenAPI document, where every endpoint records its permission as x-permission - "
        "the contract, not a description of it.",
    )
    return figure


# ---------------------------------------------------------------------------- 5. latency
def plot_latency(groups: Mapping[str, Sequence[float]], login_ms: float) -> Figure:
    figure = new_figure(16.0, 8.4)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.22, right=0.8))
    axis = figure.add_subplot(grid[0])
    ordered = sorted(groups.items(), key=lambda item: np.median(item[1]))
    for index, (name, values) in enumerate(ordered):
        data = np.array(values)
        colour = TEAL if name.startswith("POST") else SKY
        jitter = np.random.default_rng(index).uniform(-0.18, 0.18, len(data))
        axis.scatter(data, index + jitter, s=6, color=colour, alpha=0.35, linewidths=0)
        p50, p95, p99 = np.percentile(data, [50, 95, 99])
        axis.plot([p50, p50], [index - 0.3, index + 0.3], color=INK, linewidth=2)
        axis.plot([p95, p95], [index - 0.22, index + 0.22], color=AMBER, linewidth=1.6)
        axis.text(
            1.005,
            index,
            f"p50 {p50:,.0f}  p95 {p95:,.0f}  p99 {p99:,.0f} ms   n={len(data)}",
            va="center",
            transform=axis.get_yaxis_transform(),
            fontsize=7.8,
            color=INK,
        )
    axis.set_yticks(range(len(ordered)), labels=[name for name, _ in ordered], fontsize=8.4, family="monospace")
    axis.set_xscale("log")
    axis.set_xticks([5, 10, 30, 100, 300, 1000, 3000])
    axis.set_xlim(left=max(min(min(values) for values in groups.values()) * 0.8, 1))
    axis.xaxis.set_major_formatter(lambda value, _: f"{value:,.0f} ms")
    axis.xaxis.set_minor_formatter(lambda value, _: "")
    style_axes(
        axis, title="Every request of the working day (dots), its median (black) and 95th percentile (amber)", grid="x"
    )
    axis.legend(handles=[Patch(color=SKY, label="read"), Patch(color=TEAL, label="write")], loc="lower right")
    title_block(
        figure,
        "Latency, endpoint by endpoint",
        "Reads served from the modules' results take tens of milliseconds, the audit write included. Orders and "
        "pre-trade "
        f"checks re-run the mandate and search for the largest allowed order. Signing in costs {login_ms:,.0f} ms - "
        "on purpose.",
    )
    caption(
        figure,
        "In-process ASGI client, SQLite, one laptop core; the Docker deployment adds network and PostgreSQL. Sign-in "
        "is PBKDF2 at 600,000 iterations: slow for an attacker's guesses too.",
    )
    return figure


# ---------------------------------------------------------------------------- 6. the operations dashboard
@dataclass(frozen=True)
class DashboardData:
    tiles: Sequence[tuple[str, str, str]]  # label, value, colour key
    times: np.ndarray  # seconds
    by_user: Mapping[str, np.ndarray]  # requests per time bucket
    statuses: Mapping[str, int]
    latency_p50: np.ndarray
    latency_p95: np.ndarray
    routes: Sequence[tuple[str, int]]


def plot_dashboard(data: DashboardData) -> Figure:
    figure = new_figure(16.0, 9.4)
    figure.patch.set_facecolor(DARK["bg"])

    def panel(rect: tuple[float, float, float, float], title: str) -> Axes:
        axis = figure.add_axes(rect)
        axis.set_facecolor(DARK["panel"])
        for spine in axis.spines.values():
            spine.set_color(DARK["edge"])
        axis.tick_params(colors=DARK["muted"], labelsize=7.5)
        axis.set_title(title, loc="left", color=DARK["text"], fontsize=9.5, pad=6)
        axis.grid(color=DARK["edge"], linewidth=0.6)
        return axis

    figure.text(0.012, 0.962, "Meridian platform  ·  operations", color=DARK["text"], fontsize=15, weight="bold")
    figure.text(
        0.012,
        0.935,
        "The working day as Prometheus and the audit log recorded it (the provisioned Grafana dashboard shows the "
        "same series live)",
        color=DARK["muted"],
        fontsize=9,
    )
    tile_colours = {"good": "#3CCB8B", "warn": "#F2B84B", "info": "#6EA8FE", "bad": "#FF6B6B"}
    for index, (label, value, colour) in enumerate(data.tiles):
        axis = figure.add_axes((0.012 + index * 0.165, 0.78, 0.155, 0.12))
        axis.set_facecolor(DARK["panel"])
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_color(DARK["edge"])
        axis.text(0.06, 0.78, label, color=DARK["muted"], fontsize=8.5, transform=axis.transAxes)
        axis.text(0.06, 0.28, value, color=tile_colours[colour], fontsize=20, weight="bold", transform=axis.transAxes)
    rate = panel((0.04, 0.42, 0.56, 0.3), "Requests per second, by user")
    bottom = np.zeros(len(data.times))
    palette = ["#6EA8FE", "#3CCB8B", "#B794F6", "#F2B84B", "#4FD1C5", "#F687B3", "#FF6B6B", "#A0AEC0"]
    for colour, (user, series) in zip(palette, data.by_user.items(), strict=False):
        rate.fill_between(
            data.times, bottom, bottom + series, color=colour, alpha=0.75, linewidth=0, label=user, step="mid"
        )
        bottom = bottom + series
    rate.legend(
        loc="upper left", fontsize=7, ncol=4, facecolor=DARK["panel"], edgecolor=DARK["edge"], labelcolor=DARK["text"]
    )
    status = panel((0.67, 0.42, 0.31, 0.3), "Responses by status")
    names = list(data.statuses)
    values = [data.statuses[name] for name in names]
    colours = [
        "#3CCB8B" if name.startswith("2") else "#F2B84B" if name.startswith("4") else "#FF6B6B" for name in names
    ]
    status.barh(range(len(names)), values, color=colours)
    status.set_yticks(range(len(names)), labels=names)
    for index, count in enumerate(values):
        status.text(count, index, f" {count:,}", va="center", color=DARK["text"], fontsize=8)
    latency = panel((0.04, 0.06, 0.56, 0.28), "Latency p50 and p95 (ms), one-second windows")
    latency.plot(data.times, data.latency_p50, color="#6EA8FE", linewidth=1.4, label="p50")
    latency.plot(data.times, data.latency_p95, color="#F2B84B", linewidth=1.4, label="p95")
    latency.set_yscale("log")
    latency.legend(
        loc="upper right", fontsize=7.5, facecolor=DARK["panel"], edgecolor=DARK["edge"], labelcolor=DARK["text"]
    )
    latency.set_xlabel("seconds into the day", color=DARK["muted"], fontsize=8)
    routes = panel((0.8, 0.06, 0.18, 0.28), "Busiest routes")
    top = list(data.routes)[:7][::-1]
    routes.barh(range(len(top)), [count for _, count in top], color="#4FD1C5")
    routes.set_yticks(
        range(len(top)), labels=[name.replace("/v1/portfolios/{id}", "…/{id}") for name, _ in top], fontsize=7
    )
    return figure


# ---------------------------------------------------------------------------- 7. the audit chain
def plot_audit_chain(
    blocks: Sequence[tuple[int, str, str, str, int, bool]], timing: Sequence[tuple[int, float]]
) -> Figure:
    """A stretch of the chain with one record edited, and the time to verify chains of increasing length.

    ``blocks`` are (sequence, who, what, hash prefix, status, valid).
    """
    figure = new_figure(16.0, 8.8)
    axis = _canvas(figure, (0.01, 0.42, 0.98, 0.46))
    width = 0.95 / len(blocks)
    for index, (sequence, who, what, digest, status, valid) in enumerate(blocks):
        x = 0.02 + index * width
        colour = NAVY if valid else LOSS
        _box(
            axis,
            x,
            0.3,
            width * 0.82,
            0.5,
            f"#{sequence}",
            [who, what, f"status {status}", f"hash {digest}…", "✗ does not verify" if not valid else "✓ verifies"],
            colour=colour,
            size=10.5,
        )
        if index < len(blocks) - 1:
            _arrow(axis, (x + width * 0.82, 0.55), (x + width, 0.55), colour=NAVY if valid else LOSS, width=2.0)
    axis.text(
        0.02,
        0.1,
        "Record #4 was edited after the fact (its status changed). Each record stores the SHA-256 of the record "
        "before it, and its own hash covers every field "
        "together with that link: edit one record and it, and every link after it, stop verifying.",
        fontsize=9,
        color=INK,
    )
    lower = figure.add_axes((0.07, 0.08, 0.86, 0.28))
    counts = [item[0] for item in timing]
    seconds = [item[1] for item in timing]
    lower.plot(counts, seconds, color=TEAL, marker="o", linewidth=2)
    slope = np.polyfit(counts, seconds, 1)[0]
    lower.text(counts[-1], seconds[-1], f"  {slope * 1e6:,.1f} µs a record", va="center", fontsize=9, color=TEAL)
    lower.xaxis.set_major_formatter(lambda value, _: f"{value:,.0f}")
    lower.yaxis.set_major_formatter(lambda value, _: f"{value:,.2f} s")
    style_axes(
        lower, title="Verifying the whole chain: linear in its length", xlabel="records in the chain", grid="both"
    )
    title_block(
        figure,
        "A tamper-evident audit trail",
        "Every request - allowed or refused - becomes a record chained to the last by a hash. /v1/audit/verify walks "
        "the "
        "chain; readiness fails if it is broken, so a deployment with a doctored log does not take traffic.",
    )
    return figure


# ---------------------------------------------------------------------------- 8. access outcomes by user
def plot_access(rows: Sequence[tuple[str, Mapping[int, int]]]) -> Figure:
    """Each user's requests by response status."""
    figure = new_figure(16.0, 7.4)
    grid = figure.add_gridspec(1, 1, **_margins(figure, bottom=1.0, left=0.1, right=0.97))
    axis = figure.add_subplot(grid[0])
    statuses = sorted({status for _, counts in rows for status in counts})
    colour_of = {200: GAIN, 201: TEAL, 401: LOSS, 403: GOLD, 404: SLATE, 409: VIOLET, 422: AMBER, 429: "#9C7BC0"}
    left = np.zeros(len(rows))
    for status in statuses:
        values = np.array([counts.get(status, 0) for _, counts in rows], dtype=float)
        axis.barh(range(len(rows)), values, left=left, color=colour_of.get(status, SKY), label=str(status), height=0.62)
        for index, value in enumerate(values):
            if value >= 8:
                axis.text(
                    left[index] + value / 2,
                    index,
                    f"{value:,.0f}",
                    ha="center",
                    va="center",
                    fontsize=7.6,
                    color="white",
                )
        left += values
    axis.set_yticks(range(len(rows)), labels=[name for name, _ in rows], fontsize=9)
    axis.invert_yaxis()
    axis.legend(title="status", loc="lower right", ncol=4)
    style_axes(axis, title="Each person's requests by the platform's answer", grid="x")
    title_block(
        figure,
        "Who was refused, and why",
        "401: no valid token (the intruder's guesses and forged token). 403: signed in, but not permitted (the client "
        "reaching for the risk model). 404: not entitled, answered as if absent. 422: the mandate blocked the order.",
    )
    caption(
        figure,
        "From the audit log of the working day: every request is there, including the ones that never reached a "
        "handler.",
    )
    return figure


# ---------------------------------------------------------------------------- 9. four eyes
def plot_four_eyes(counts: Mapping[str, int], threshold: float) -> Figure:
    figure = new_figure(16.0, 7.6)
    axis = _canvas(figure, (0.01, 0.04, 0.98, 0.82))
    _box(
        axis,
        0.02,
        0.4,
        0.14,
        0.2,
        "Order entered",
        [f"{counts.get('entered', 0)} orders", "PM or trader"],
        colour=SLATE,
    )
    _box(
        axis, 0.24, 0.4, 0.16, 0.2, "Pre-trade check", ["the Day 6 mandate", "on the resulting portfolio"], colour=NAVY
    )
    _box(
        axis,
        0.24,
        0.05,
        0.16,
        0.2,
        "Blocked",
        [f"{counts.get('blocked', 0)} orders", "422 + largest allowed"],
        colour=LOSS,
    )
    _box(
        axis,
        0.5,
        0.68,
        0.17,
        0.2,
        "Approved",
        [f"{counts.get('direct', 0)} orders", f"under {threshold:,.0f}"],
        colour=GAIN,
    )
    _box(
        axis,
        0.5,
        0.3,
        0.17,
        0.2,
        "Pending approval",
        [f"{counts.get('pending', 0)} orders", f"over {threshold:,.0f}"],
        colour=GOLD,
    )
    _box(
        axis,
        0.78,
        0.45,
        0.19,
        0.2,
        "Approved by a second person",
        [f"{counts.get('approved', 0)} orders", "compliance officer"],
        colour=GAIN,
    )
    _box(
        axis,
        0.78,
        0.1,
        0.19,
        0.2,
        "Rejected",
        [f"{counts.get('rejected', 0)} orders", "with the reason recorded"],
        colour=LOSS,
    )
    _box(axis, 0.78, 0.8, 0.19, 0.14, "Self-approval", ["refused: 403"], colour=VIOLET)
    _arrow(axis, (0.16, 0.5), (0.24, 0.5))
    _arrow(axis, (0.32, 0.4), (0.32, 0.25), colour=LOSS)
    _arrow(axis, (0.4, 0.55), (0.5, 0.76), colour=GAIN)
    _arrow(axis, (0.4, 0.46), (0.5, 0.42), colour=GOLD)
    _arrow(axis, (0.67, 0.43), (0.78, 0.53), colour=GAIN)
    _arrow(axis, (0.67, 0.37), (0.78, 0.2), colour=LOSS)
    _arrow(axis, (0.62, 0.5), (0.8, 0.8), colour=VIOLET, style="-[", curve=-0.2)
    title_block(
        figure,
        "Orders under four eyes",
        "Every order is checked against the mandate before it exists; above the threshold, or where the mandate needs "
        "an "
        "override, it waits for a second person - never the one who entered it. Counts from the working day.",
    )
    return figure


# ---------------------------------------------------------------------------- 10. deployment
def plot_deployment() -> Figure:
    figure = new_figure(16.0, 8.4)
    axis = _canvas(figure, (0.01, 0.03, 0.98, 0.84))
    axis.add_patch(
        FancyBboxPatch(
            (0.02, 0.05),
            0.96,
            0.74,
            boxstyle="round,pad=0.004,rounding_size=0.015",
            facecolor="#F4F7FB",
            edgecolor=SLATE,
            linewidth=1.2,
            linestyle="--",
        )
    )
    axis.text(0.035, 0.76, "docker compose  ·  network meridian_default", fontsize=10, weight="bold", color=SLATE)
    axis.text(0.035, 0.97, "The host", fontsize=10, weight="bold", color=INK)
    for x, name, detail in (
        (0.43, "localhost:8000", "/docs  ·  /v1/*"),
        (0.62, "localhost:9090", "Prometheus UI"),
        (0.81, "localhost:3000", "Grafana dashboard"),
    ):
        _box(axis, x, 0.83, 0.16, 0.11, name, [detail], colour="#EEF3FA", fill="#EEF3FA", text=NAVY, size=9.5)
    _arrow(axis, (0.51, 0.83), (0.51, 0.72), colour=NAVY)
    _arrow(axis, (0.7, 0.83), (0.78, 0.72), colour=VIOLET)
    _arrow(axis, (0.965, 0.83), (0.945, 0.3), colour=TEAL)
    _box(
        axis,
        0.06,
        0.45,
        0.2,
        0.26,
        "db",
        ["postgres:16-alpine", "volume pgdata", "healthcheck pg_isready"],
        colour=INK,
        size=10,
    )
    _box(
        axis,
        0.06,
        0.1,
        0.2,
        0.22,
        "migrate",
        ["alembic upgrade head", "runs once, then exits", "0001 → 0009"],
        colour=SLATE,
        size=10,
    )
    _box(
        axis,
        0.4,
        0.36,
        0.22,
        0.36,
        "api",
        ["meridian-platform:1.4.0", "uvicorn, 2 workers", "non-root, read-only code", "HEALTHCHECK /health", ":8000"],
        colour=NAVY,
        size=10,
    )
    _box(axis, 0.74, 0.5, 0.2, 0.22, "prometheus", ["scrapes /metrics", "every 5 s", ":9090"], colour=VIOLET, size=10)
    _box(
        axis,
        0.74,
        0.15,
        0.2,
        0.26,
        "grafana",
        ["provisioned datasource", "Meridian dashboard", ":3000"],
        colour=TEAL,
        size=10,
    )
    _arrow(axis, (0.16, 0.32), (0.16, 0.45), colour=SLATE)
    axis.text(0.17, 0.37, "schema", fontsize=8, color=SLATE)
    _arrow(axis, (0.4, 0.56), (0.26, 0.56), colour=INK)
    axis.text(0.28, 0.58, "SQL", fontsize=8, color=INK)
    _arrow(axis, (0.74, 0.65), (0.62, 0.6), colour=VIOLET)
    axis.text(0.64, 0.66, "scrape", fontsize=8, color=VIOLET)
    _arrow(axis, (0.84, 0.41), (0.84, 0.55), colour=TEAL)
    _arrow(axis, (0.26, 0.2), (0.4, 0.45), colour=SLATE, style="-|>", curve=0.2)
    axis.text(0.29, 0.29, "completes before\napi starts", fontsize=7.6, color=SLATE)
    title_block(
        figure,
        "Deployment: the whole platform with one command",
        "docker compose up --build: PostgreSQL, a migration job that must succeed before the API starts, the API image "
        "(multi-stage, no compiler, a user without root, its own health check), and Prometheus with Grafana.",
    )
    return figure


# ---------------------------------------------------------------------------- 11. growth
def plot_growth(rows: Sequence[Mapping[str, object]]) -> Figure:
    figure = new_figure(16.0, 8.6)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.5, 1.0], wspace=0.22, **_margins(figure, bottom=1.1))
    axis = figure.add_subplot(grid[0])
    x = np.arange(len(rows))
    source = np.array([row["source_lines"] for row in rows], dtype=float)
    tests = np.array([row["test_lines"] for row in rows], dtype=float)
    axis.fill_between(x, 0, source, color=NAVY, alpha=0.85, label="source lines", step=None)
    axis.fill_between(x, source, source + tests, color=TEAL, alpha=0.75, label="test lines")
    for index, row in enumerate(rows):
        axis.text(
            index,
            source[index] + tests[index] + 1200,
            str(row["module"]),
            rotation=35,
            ha="left",
            va="bottom",
            fontsize=8,
            color=INK,
        )
    axis.set_xticks(x, labels=[str(row["tag"]) for row in rows], fontsize=8)
    axis.yaxis.set_major_formatter(lambda value, _: f"{value / 1000:,.0f}k")
    axis.set_ylim(0, (source + tests).max() * 1.2)
    axis.legend(loc="upper left")
    style_axes(axis, title="Lines of code at each release (non-blank)", grid="y")
    side = figure.add_subplot(grid[1])
    for key, colour, label in (
        ("tests", TEAL, "test functions"),
        ("figures", VIOLET, "figures"),
        ("decisions", AMBER, "decision records"),
        ("notes", SKY, "methodology notes"),
    ):
        values = np.array([row[key] for row in rows], dtype=float)
        side.plot(
            x, values / values.max(), color=colour, marker="o", markersize=4, label=f"{label} ({values[-1]:,.0f})"
        )
    side.set_xticks(x, labels=[str(row["tag"]).removeprefix("v").removesuffix(".0") for row in rows], fontsize=7.5)
    side.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    side.legend(loc="lower right")
    style_axes(side, title="Everything else, as a share of where it ended", grid="both")
    first, last = rows[0], rows[-1]
    title_block(
        figure,
        "Nine days, ten releases",
        f"From {first['source_lines']:,} lines of source and {first['tests']:,} tests at {first['tag']} to "
        f"{last['source_lines']:,} "
        f"and {last['tests']:,} at {last['tag']} - every release an issue, a branch, a pull request with green CI, "
        "and a tag.",
    )
    caption(
        figure,
        "Measured from each tag's git archive by meridian.devtools.growth (tests counted by parsing, before "
        "parametrisation).",
    )
    return figure


# ---------------------------------------------------------------------------- 12. the module graph
def plot_module_graph(
    layers: Sequence[Sequence[str]],
    sizes: Mapping[str, int],
    edges: Mapping[tuple[str, str], int],
    upward: Sequence[tuple[str, str]] = (),
) -> Figure:
    figure = new_figure(16.0, 9.6)
    axis = _canvas(figure, (0.01, 0.03, 0.98, 0.84))
    position: dict[str, tuple[float, float]] = {}
    for level, names in enumerate(layers):
        y = 0.08 + level * (0.84 / max(len(layers) - 1, 1))
        for index, name in enumerate(names):
            position[name] = ((index + 1) / (len(names) + 1), y)
    biggest = max(sizes.values())
    for (source, target), weight in edges.items():
        if source not in position or target not in position:
            continue
        (x0, y0), (x1, y1) = position[source], position[target]
        against = (source, target) in upward
        axis.add_patch(
            FancyArrowPatch(
                (x0, y0),
                (x1, y1),
                arrowstyle="-|>",
                mutation_scale=8 if not against else 14,
                color=LOSS if against else SLATE,
                alpha=0.9 if against else min(0.12 + weight / 60, 0.55),
                linewidth=2.2 if against else 0.5 + weight / 12,
                connectionstyle="arc3,rad=0.06",
                shrinkA=18,
                shrinkB=18,
                zorder=2 if against else 1,
            )
        )
    colours = [INK, SLATE, SKY, VIOLET, TEAL, NAVY, AMBER]
    for level, names in enumerate(layers):
        for name in names:
            x, y = position[name]
            radius = 0.018 + 0.03 * (sizes.get(name, 0) / biggest) ** 0.5
            axis.add_patch(
                FancyBboxPatch(
                    (x - radius * 1.6, y - radius * 0.7),
                    radius * 3.2,
                    radius * 1.4,
                    boxstyle="round,pad=0,rounding_size=0.01",
                    facecolor=colours[level % len(colours)],
                    edgecolor="white",
                    linewidth=1.5,
                    zorder=3,
                )
            )
            axis.text(
                x, y + 0.004, name, ha="center", va="center", color="white", fontsize=8.6, weight="bold", zorder=4
            )
            axis.text(
                x,
                y - radius * 0.7 - 0.012,
                f"{sizes.get(name, 0):,} lines",
                ha="center",
                va="top",
                fontsize=7,
                color=MUTED,
                zorder=4,
            )
    verdict = (
        "every import points down"
        if not upward
        else f"{len(upward)} import{'s' if len(upward) != 1 else ''} against the layers (red)"
    )
    title_block(
        figure,
        f"The package graph: {verdict}",
        f"Parsed from the source: {len(edges)} package-to-package dependencies. core imports nothing from the "
        "platform; "
        "the domain and the analytics import only core; the API, the command line and the charts sit on top. "
        "Edge width: import statements.",
    )
    return figure


# ---------------------------------------------------------------------------- 13. the tests
def plot_tests(
    rows: Sequence[tuple[str, int, int]], total_collected: int, controls: Sequence[tuple[str, str]]
) -> Figure:
    figure = new_figure(16.0, 8.2)
    grid = figure.add_gridspec(1, 2, width_ratios=[1.4, 1.0], wspace=0.25, **_margins(figure, bottom=1.0, left=0.1))
    axis = figure.add_subplot(grid[0])
    ordered = sorted(rows, key=lambda row: row[1])
    positions = np.arange(len(ordered))
    axis.barh(positions, [row[1] - row[2] for row in ordered], color=NAVY, height=0.65, label="example-based")
    axis.barh(
        positions,
        [row[2] for row in ordered],
        left=[row[1] - row[2] for row in ordered],
        color=AMBER,
        height=0.65,
        label="property-based (Hypothesis)",
    )
    for index, row in enumerate(ordered):
        axis.text(row[1] + 1, index, f"{row[1]}", va="center", fontsize=8)
    axis.set_yticks(positions, labels=[row[0] for row in ordered], fontsize=8.6)
    axis.legend(loc="lower right")
    style_axes(axis, title="Test functions by area", grid="x")
    side = figure.add_subplot(grid[1])
    side.axis("off")
    side.set_title("What CI runs on every pull request", loc="left")
    for index, (name, detail) in enumerate(controls):
        y = 0.92 - index * 0.105
        side.add_patch(
            FancyBboxPatch(
                (0.0, y - 0.035),
                0.06,
                0.07,
                boxstyle="round,pad=0,rounding_size=0.01",
                facecolor=GAIN,
                edgecolor="none",
                transform=side.transAxes,
            )
        )
        side.text(
            0.03, y, "✓", color="white", ha="center", va="center", fontsize=10, weight="bold", transform=side.transAxes
        )
        side.text(0.09, y + 0.012, name, fontsize=9.4, weight="bold", color=INK, transform=side.transAxes)
        side.text(0.09, y - 0.028, detail, fontsize=8, color=MUTED, transform=side.transAxes)
    title_block(
        figure,
        f"{total_collected:,} tests, and what they guard",
        "Unit tests, property tests over generated inputs for the invariants that must hold for every input, "
        "integration tests against PostgreSQL 16, end-to-end tests of the command line and the API.",
    )
    return figure


# ---------------------------------------------------------------------------- 14. security controls
def plot_security(rows: Sequence[tuple[str, str, str]]) -> Figure:
    """OWASP API Security Top 10 (2023): (risk, the control here, the test that proves it)."""
    figure = new_figure(16.0, 1.8 + 0.62 * len(rows))
    axis = _canvas(figure, (0.01, 0.02, 0.98, 0.86))
    step = 0.96 / (len(rows) + 1)
    for x, header in ((0.0, "OWASP API Security Top 10 (2023)"), (0.33, "Control in Meridian"), (0.74, "Proved by")):
        axis.text(x, 0.98, header, fontsize=9.5, weight="bold", color=MUTED)
    for index, (risk, control, proof) in enumerate(rows):
        y = 0.98 - (index + 1) * step
        if index % 2 == 0:
            axis.add_patch(
                FancyBboxPatch(
                    (-0.005, y - step * 0.45),
                    1.0,
                    step * 0.9,
                    boxstyle="round,pad=0,rounding_size=0.004",
                    facecolor=BAND,
                    edgecolor="none",
                )
            )
        axis.text(0.0, y, risk, fontsize=9, color=INK, va="center", weight="bold")
        axis.text(0.33, y, control, fontsize=8.6, color=INK, va="center")
        axis.text(0.74, y, proof, fontsize=8, color=TEAL, va="center", family="monospace")
    title_block(
        figure,
        "Security controls, mapped to the OWASP API Top 10",
        "Each risk, what the platform does about it, and the test that fails if it stops doing it.",
    )
    return figure


# ---------------------------------------------------------------------------- 15. the journey
def plot_journey(panels: Sequence[tuple[str, str, str, np.ndarray | None]]) -> Figure:
    """The nine days: (day, module, headline, image)."""
    figure = new_figure(16.0, 11.2)
    grid = figure.add_gridspec(3, 3, hspace=0.32, wspace=0.08, top=0.87, bottom=0.03, left=0.015, right=0.985)
    for index, (day, module, headline, image) in enumerate(panels):
        axis = figure.add_subplot(grid[divmod(index, 3)])
        if image is not None:
            axis.imshow(image)
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_color(GRID)
        axis.set_title(f"{day}  ·  {module}", loc="left", fontsize=10, color=NAVY, weight="bold", pad=18)
        axis.text(0.0, 1.015, headline, transform=axis.transAxes, fontsize=8, color=MUTED, va="bottom")
    title_block(
        figure,
        "Nine days: from money and calendars to a platform",
        "Each day one module - built on the ones before, with its own charts, notes, decisions, migrations and tests - "
        "and on the ninth, one API over all of them.",
    )
    return figure
