"""Shared callback-data constants.

The main menu emits these top-level callbacks; each feature module registers a
handler for its own constant on its router. Modules use their own prefixed
callback data internally (e.g. ``files:...``, ``cal:...``, ``ai:...``, ``fc:...``).
"""
from __future__ import annotations

MENU_HOME = "menu:home"
MENU_FILES = "menu:files"
MENU_CALENDAR = "menu:calendar"
MENU_AI = "menu:ai"
MENU_FACEIT = "menu:faceit"
