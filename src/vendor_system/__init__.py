"""vendor_system - Vendor Order System with an automated restock bot.

A capstone that packages the Week 4 Vendor Order backend together with the
Week 5 automation work, presented in a single Tkinter dashboard.

    from vendor_system import database as db
    from vendor_system.restock_bot import RestockBot, scan_once
"""

from . import database
from .restock_bot import (DEFAULT_INTERVAL, DEFAULT_TARGET_FACTOR, RestockBot,
                          restock_quantity, scan_once, setup_logging,
                          summarise_report)

__version__ = "1.0.0"
__all__ = ["database", "RestockBot", "scan_once", "restock_quantity",
           "summarise_report", "setup_logging",
           "DEFAULT_INTERVAL", "DEFAULT_TARGET_FACTOR"]
