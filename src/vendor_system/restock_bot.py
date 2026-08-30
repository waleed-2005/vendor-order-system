"""
Vendor Order System - the automated restock bot.

WHAT IT DOES
------------
The Week 4 system could TELL you something was low. This bot ACTS on it. On a
schedule it scans every product, and for anything at or below its reorder level
it raises a restock order automatically, so the vendor does not have to notice
the problem first.

HOW MUCH TO ORDER
-----------------
Ordering exactly enough to reach the reorder level would leave the product on
the edge, and it would be flagged again on the very next scan. The bot instead
orders up to a TARGET LEVEL, calculated as the reorder level multiplied by a
factor (2 by default) - so a product that reorders at 10 is topped up to 20.
The amount ordered is therefore:

    quantity = target_level - current_stock

NOT ORDERING THE SAME THING TWICE
---------------------------------
A restock order takes time to arrive. Without a check, the bot would flag the
same product on every single scan and the vendor would end up with a pile of
duplicate orders. Before flagging anything the bot therefore looks for an
outstanding ('Flagged') order for that product, and skips it if one exists.
This is the same "act on a change of state, not on a condition" idea used for
the Week 3 alerts.

LOGGING
-------
Every scan and every decision is written to a log file through the logging
module, with levels: INFO for a normal scan, WARNING when something is flagged,
and ERROR if a restock order cannot be raised. Because the log is timestamped
and on disk, there is a permanent record of what the bot did and when.
"""

import logging
import os
import threading
from datetime import datetime

from . import database as db

LOG_FILE = os.path.join(os.path.expanduser("~"), "restock_bot.log")

DEFAULT_INTERVAL = 30       # seconds between automatic scans
DEFAULT_TARGET_FACTOR = 2.0  # top up to reorder_level x this


def setup_logging(log_file=LOG_FILE):
    """Configure a named logger that writes timestamped entries to a file."""
    logger = logging.getLogger("restock_bot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    return logger


log = logging.getLogger("restock_bot")


# ===========================================================================
#  THE DECISION LOGIC  (pure functions - no threads, no GUI, easy to test)
# ===========================================================================
def restock_quantity(product, target_factor=DEFAULT_TARGET_FACTOR):
    """How many units to order so the product reaches its target level.

    Returns 0 if the product does not need restocking at all.
    """
    if product["stock"] > product["reorder_level"]:
        return 0
    target = max(1, int(round(product["reorder_level"] * target_factor)))
    return max(0, target - product["stock"])


def scan_once(target_factor=DEFAULT_TARGET_FACTOR, dry_run=False,
              db_name=db.DB_NAME):
    """Run a single scan of every product.

    Returns a report dict:
        checked  - how many products were looked at
        flagged  - list of (product, quantity) newly ordered
        skipped  - list of products low but already on order
        errors   - list of problems encountered

    dry_run=True works out what WOULD be ordered without writing anything,
    which is what the dashboard's "Preview" uses.
    """
    report = {"checked": 0, "flagged": [], "skipped": [], "errors": [],
              "at": datetime.now().strftime("%H:%M:%S")}

    try:
        products = db.get_products(db_name)
    except Exception as e:                      # database unreadable
        report["errors"].append(f"Could not read products: {e}")
        log.error("Scan failed - could not read products: %s", e)
        return report

    report["checked"] = len(products)

    for product in products:
        quantity = restock_quantity(product, target_factor)
        if quantity <= 0:
            continue                            # healthy stock, nothing to do

        # Do not raise a second order for something already on order.
        existing = db.open_restock_order(product["id"], db_name)
        if existing:
            report["skipped"].append(product)
            log.info("SKIP  %s - already on order (restock #%s)",
                     product["name"], existing["id"])
            continue

        if dry_run:
            report["flagged"].append((product, quantity))
            continue

        try:
            restock_id = db.create_restock_order(product["id"], quantity,
                                                 "bot", db_name)
        except (ValueError, db.NotFoundError) as e:
            report["errors"].append(f"{product['name']}: {e}")
            log.error("Could not raise a restock order for %s: %s",
                      product["name"], e)
            continue

        report["flagged"].append((product, quantity))
        log.warning("FLAG  %s - stock %s at/below reorder level %s "
                    "-> ordered %s (restock #%s)",
                    product["name"], product["stock"],
                    product["reorder_level"], quantity, restock_id)

    log.info("Scan complete - %s product(s) checked, %s flagged, %s skipped",
             report["checked"], len(report["flagged"]), len(report["skipped"]))
    return report


def summarise_report(report):
    """A one-line human summary of a scan report."""
    if report["errors"]:
        return (f"Scan finished with {len(report['errors'])} problem(s) - "
                f"{len(report['flagged'])} flagged.")
    if report["flagged"]:
        names = ", ".join(f"{p['name']} (+{q})" for p, q in report["flagged"])
        return (f"Checked {report['checked']} product(s) - "
                f"ordered restocks for {names}.")
    if report["skipped"]:
        return (f"Checked {report['checked']} product(s) - "
                f"{len(report['skipped'])} low but already on order.")
    return f"Checked {report['checked']} product(s) - all stock levels healthy."


# ===========================================================================
#  THE SCHEDULER  (runs scan_once repeatedly on a background timer)
# ===========================================================================
class RestockBot:
    """Runs scan_once() on a repeating schedule in the background.

    A threading.Timer is used rather than a sleep loop so that stopping the bot
    is immediate and the interface never has to wait for a sleep to finish.
    """

    def __init__(self, interval=DEFAULT_INTERVAL,
                 target_factor=DEFAULT_TARGET_FACTOR,
                 on_report=None, db_name=db.DB_NAME):
        self.interval = interval
        self.target_factor = target_factor
        self.on_report = on_report          # called with each scan report
        self.db_name = db_name
        self._timer = None
        self._lock = threading.Lock()
        self.running = False
        self.scans = 0

    def start(self):
        if self.running:
            return
        self.running = True
        log.info("Bot started - scanning every %s seconds", self.interval)
        self._run_scan()                    # scan immediately, then schedule

    def stop(self):
        with self._lock:
            self.running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
        log.info("Bot stopped after %s scan(s)", self.scans)

    def scan_now(self):
        """Run one scan straight away, whether or not the bot is running."""
        return self._do_scan()

    # ------------------------------------------------------------ internals
    def _do_scan(self):
        report = scan_once(self.target_factor, db_name=self.db_name)
        self.scans += 1
        if self.on_report:
            try:
                self.on_report(report)
            except Exception as e:          # a broken callback must not kill the bot
                log.error("Report callback failed: %s", e)
        return report

    def _run_scan(self):
        if not self.running:
            return
        self._do_scan()
        with self._lock:
            if self.running:
                self._timer = threading.Timer(self.interval, self._run_scan)
                self._timer.daemon = True   # never blocks the program from exiting
                self._timer.start()
