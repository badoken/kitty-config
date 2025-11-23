# pyright: reportMissingImports=false
from datetime import datetime
from time import monotonic
import json
import subprocess

from kitty.boss import get_boss
from kitty.fast_data_types import Screen, add_timer, get_options
from kitty.utils import color_as_int
from kitty.tab_bar import (
    DrawData,
    ExtraData,
    Formatter,
    TabBarData,
    as_rgb,
    draw_attributed_string,
    draw_title,
)

opts = get_options()
icon_fg = as_rgb(color_as_int(opts.color16))
icon_bg = as_rgb(color_as_int(opts.color8))
bat_text_color = as_rgb(color_as_int(opts.color15))
clock_color = as_rgb(color_as_int(opts.color15))
date_color = as_rgb(color_as_int(opts.color8))
SEPARATOR_SYMBOL, SOFT_SEPARATOR_SYMBOL = ("", "")
RIGHT_MARGIN = 1
REFRESH_TIME = 1

# Taskwarrior-related UI
working_color = as_rgb(color_as_int(opts.color2))
ICON_ACTIVE = "󰑮"
ICON_INACTIVE = ""

# Cache Taskwarrior status so we don't shell out too often
TASK_REFRESH_SECONDS = 2.0
_last_task_check = 0.0
_last_has_active_task = False
_last_task_id = None
_last_task_start = None


def _parse_task_datetime(value: str):
    """Best-effort parse of Taskwarrior datetime string into a naive datetime.

    Taskwarrior usually uses formats like YYYYMMDDTHHMMSS or YYYYMMDDTHHMMSSZ.
    We ignore timezone and treat it as local time for relative calculations.
    """

    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _update_task_cache() -> None:
    """Refresh cached Taskwarrior info (id + start time of an active task)."""

    global _last_task_check, _last_has_active_task, _last_task_id, _last_task_start

    now = monotonic()
    if now - _last_task_check < TASK_REFRESH_SECONDS:
        return

    _last_task_check = now
    try:
        proc = subprocess.run(
            ["task", "+ACTIVE", "export"],
            capture_output=True,
            text=True,
            timeout=0.5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _last_has_active_task = False
        _last_task_id = None
        _last_task_start = None
        return

    if proc.returncode != 0 or not proc.stdout.strip():
        _last_has_active_task = False
        _last_task_id = None
        _last_task_start = None
        return

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        _last_has_active_task = False
        _last_task_id = None
        _last_task_start = None
        return

    if not data:
        _last_has_active_task = False
        _last_task_id = None
        _last_task_start = None
        return

    task = data[0]
    _last_task_id = task.get("id")
    _last_task_start = _parse_task_datetime(task.get("start", ""))
    _last_has_active_task = _last_task_id is not None and _last_task_start is not None


def get_task_display_fields():
    _update_task_cache()

    if not _last_has_active_task:
        # No active task: reserve the space but leave id/time blank
        return [(" _", icon_fg), (ICON_INACTIVE, icon_fg), ("  :  ", icon_fg)]

    # ID: clamp to 1–99 and render into a 2-char field
    try:
        task_id_int = int(_last_task_id)
    except (TypeError, ValueError):
        task_id_int = 0
    if task_id_int <= 0:
        id_str = "  "
    else:
        task_id_int = min(task_id_int, 99)
        id_str = f"{task_id_int:2d}"

    # Elapsed time since "start" in hh:mm, capped at 99h
    elapsed_str = "     "
    if _last_task_start is not None:
        delta = datetime.now() - _last_task_start
        total_minutes = max(int(delta.total_seconds() // 60), 0)
        hours = min(total_minutes // 60, 99)
        minutes = total_minutes % 60
        elapsed_str = f"{hours:02d}:{minutes:02d}"

    return [(id_str, icon_fg), (ICON_ACTIVE, working_color), (elapsed_str, icon_fg)]

UNPLUGGED_ICONS = {
    10: "󰁺",
    20: "󰁻",
    30: "󰁼",
    40: "󰁽",
    50: "󰁾",
    60: "󰁿",
    70: "󰂀",
    80: "󰂁",
    90: "󰂂",
    100: "󰁹",
}
PLUGGED_ICONS = {
    1: "󰂄",
}
UNPLUGGED_COLORS = {
    15: as_rgb(color_as_int(opts.color1)),
    16: as_rgb(color_as_int(opts.color15)),
}
PLUGGED_COLORS = {
    15: as_rgb(color_as_int(opts.color1)),
    16: as_rgb(color_as_int(opts.color6)),
    99: as_rgb(color_as_int(opts.color6)),
    100: as_rgb(color_as_int(opts.color2)),
}


def _draw_task(screen: Screen, index: int) -> int:
    """Draw the Taskwarrior block: "NN ICON hh:mm"."""

    if index != 1:
        return 0

    all_elements = ""
    for element, color in get_task_display_fields():
        fg, bg = screen.cursor.fg, screen.cursor.bg
        screen.cursor.fg = color
        screen.cursor.bg = icon_bg
        element_on_tab = f"{element} "
        screen.draw(element_on_tab)
        screen.cursor.fg, screen.cursor.bg = fg, bg
        all_elements += element_on_tab

    # Reserve the full width for id + icon + time
    screen.cursor.x = len(all_elements) 
    return screen.cursor.x


def _draw_left_status(
    draw_data: DrawData,
    screen: Screen,
    tab: TabBarData,
    before: int,
    max_title_length: int,
    index: int,
    is_last: bool,
    extra_data: ExtraData,
) -> int:
    if screen.cursor.x >= screen.columns - right_status_length:
        return screen.cursor.x
    tab_bg = screen.cursor.bg
    tab_fg = screen.cursor.fg
    default_bg = as_rgb(int(draw_data.default_bg))
    if extra_data.next_tab:
        next_tab_bg = as_rgb(draw_data.tab_bg(extra_data.next_tab))
        needs_soft_separator = next_tab_bg == tab_bg
    else:
        next_tab_bg = default_bg
        needs_soft_separator = False

    screen.draw(" ")
    screen.cursor.bg = tab_bg
    draw_title(draw_data, screen, tab, index)
    if not needs_soft_separator:
        screen.draw(" ")
        screen.cursor.fg = tab_bg
        screen.cursor.bg = next_tab_bg
        screen.draw(SEPARATOR_SYMBOL)
    else:
        prev_fg = screen.cursor.fg
        if tab_bg == tab_fg:
            screen.cursor.fg = default_bg
        elif tab_bg != default_bg:
            c1 = draw_data.inactive_bg.contrast(draw_data.default_bg)
            c2 = draw_data.inactive_bg.contrast(draw_data.inactive_fg)
            if c1 < c2:
                screen.cursor.fg = default_bg
        screen.draw(" " + SOFT_SEPARATOR_SYMBOL)
        screen.cursor.fg = prev_fg
    end = screen.cursor.x
    return end


def _draw_right_status(screen: Screen, is_last: bool, cells: list) -> int:
    if not is_last:
        return 0
    draw_attributed_string(Formatter.reset, screen)
    screen.cursor.x = screen.columns - right_status_length
    screen.cursor.fg = 0
    for color, status in cells:
        screen.cursor.fg = color
        screen.draw(status)
    screen.cursor.bg = 0
    return screen.cursor.x


def _redraw_tab_bar(_):
    tm = get_boss().active_tab_manager
    if tm is not None:
        tm.mark_tab_bar_dirty()


def get_battery_cells() -> list:
    try:
        with open("/sys/class/power_supply/BAT0/status", "r") as f:
            status = f.read()
        with open("/sys/class/power_supply/BAT0/capacity", "r") as f:
            percent = int(f.read())
        if status == "Discharging\n":
            icon_color = UNPLUGGED_COLORS[
                min(UNPLUGGED_COLORS.keys(), key=lambda x: abs(x - percent))
            ]
            icon = UNPLUGGED_ICONS[
                min(UNPLUGGED_ICONS.keys(), key=lambda x: abs(x - percent))
            ]
        elif status == "Not charging\n":
            icon_color = UNPLUGGED_COLORS[
                min(UNPLUGGED_COLORS.keys(), key=lambda x: abs(x - percent))
            ]
            icon = PLUGGED_ICONS[
                min(PLUGGED_ICONS.keys(), key=lambda x: abs(x - percent))
            ]
        else:
            icon_color = PLUGGED_COLORS[
                min(PLUGGED_COLORS.keys(), key=lambda x: abs(x - percent))
            ]
            icon = PLUGGED_ICONS[
                min(PLUGGED_ICONS.keys(), key=lambda x: abs(x - percent))
            ]
        percent_cell = (bat_text_color, str(percent) + "% ")
        icon_cell = (icon_color, icon)
        return [percent_cell, icon_cell]
    except FileNotFoundError:
        return []


timer_id = None
right_status_length = -1

def draw_tab(
    draw_data: DrawData,
    screen: Screen,
    tab: TabBarData,
    before: int,
    max_title_length: int,
    index: int,
    is_last: bool,
    extra_data: ExtraData,
) -> int:
    global timer_id
    global right_status_length
    if timer_id is None:
        timer_id = add_timer(_redraw_tab_bar, REFRESH_TIME, True)
    clock = datetime.now().strftime(" %H:%M")
    date = datetime.now().strftime(" %d.%m.%y")
    cells = get_battery_cells()
    cells.append((clock_color, clock))
    cells.append((date_color, date))
    right_status_length = RIGHT_MARGIN
    for cell in cells:
        right_status_length += len(str(cell[1]))

    _draw_task(screen, index)
    _draw_left_status(
        draw_data,
        screen,
        tab,
        before,
        max_title_length,
        index,
        is_last,
        extra_data,
    )
    _draw_right_status(
        screen,
        is_last,
        cells,
    )
    return screen.cursor.x
