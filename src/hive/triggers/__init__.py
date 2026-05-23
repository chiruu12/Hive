"""Trigger systems for Hive agents."""

from hive.triggers.base import Trigger
from hive.triggers.hotkey import HotkeyTrigger
from hive.triggers.webhook import WebhookTrigger

__all__ = ["HotkeyTrigger", "Trigger", "WebhookTrigger"]
