"""pytest suite for the Vendor Order System capstone.

Covers the Week 4 backend, the Week 5 automation, and the way they interact.
Every test gets its own temporary database, so they never affect each other or
the user's real data.
"""

import pytest

from vendor_system import database as db
from vendor_system.restock_bot import (RestockBot, restock_quantity, scan_once,
                                       summarise_report)


@pytest.fixture
def dbf(tmp_path):
    """A fresh, seeded database for each test."""
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


# =========================================================== Week 4 backend
def test_seed_creates_products(dbf):
    assert len(db.get_products(dbf)) == 5


def test_two_products_start_low(dbf):
    assert len(db.low_stock_products(dbf)) == 2


def test_order_deducts_stock(dbf):
    product = db.get_products(dbf)[0]
    before = product["stock"]
    db.create_order("Test Co", product["id"], 5, dbf)
    assert db.get_product(product["id"], dbf)["stock"] == before - 5


def test_overselling_is_refused(dbf):
    low = db.low_stock_products(dbf)[0]
    with pytest.raises(db.OutOfStockError):
        db.create_order("Greedy", low["id"], low["stock"] + 100, dbf)


def test_stock_unchanged_after_refusal(dbf):
    low = db.low_stock_products(dbf)[0]
    before = low["stock"]
    with pytest.raises(db.OutOfStockError):
        db.create_order("Greedy", low["id"], before + 100, dbf)
    assert db.get_product(low["id"], dbf)["stock"] == before


def test_deleting_order_returns_stock(dbf):
    product = db.get_products(dbf)[0]
    before = product["stock"]
    order_id = db.create_order("Test Co", product["id"], 4, dbf)
    db.delete_order(order_id, True, dbf)
    assert db.get_product(product["id"], dbf)["stock"] == before


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_product_name_rejected(bad, dbf):
    with pytest.raises(ValueError):
        db.add_product(bad, 10, db_name=dbf)


def test_sql_injection_is_blocked(dbf):
    db.add_product("x'; DROP TABLE products; --", 5, db_name=dbf)
    assert len(db.get_products(dbf)) == 6      # table survived


# ======================================================== Week 5 automation
def test_restock_quantity_tops_up_to_target(dbf):
    low = db.low_stock_products(dbf)[0]
    expected = low["reorder_level"] * 2 - low["stock"]
    assert restock_quantity(low, 2.0) == expected


def test_healthy_product_needs_no_restock(dbf):
    healthy = [p for p in db.get_products(dbf)
               if p["stock"] > p["reorder_level"]][0]
    assert restock_quantity(healthy) == 0


def test_scan_flags_low_products(dbf):
    report = scan_once(db_name=dbf)
    assert len(report["flagged"]) == 2
    assert not report["errors"]


def test_scan_does_not_duplicate_orders(dbf):
    scan_once(db_name=dbf)
    second = scan_once(db_name=dbf)
    assert second["flagged"] == []
    assert len(second["skipped"]) == 2
    assert len(db.get_restock_orders(db_name=dbf)) == 2


def test_dry_run_changes_nothing(dbf):
    report = scan_once(dry_run=True, db_name=dbf)
    assert report["flagged"]                     # it found something
    assert db.get_restock_orders(db_name=dbf) == []   # but wrote nothing


def test_receiving_restock_adds_stock(dbf):
    scan_once(db_name=dbf)
    order = db.get_restock_orders("Flagged", dbf)[0]
    before = db.get_product(order["product_id"], dbf)["stock"]
    db.receive_restock_order(order["id"], dbf)
    after = db.get_product(order["product_id"], dbf)["stock"]
    assert after == before + order["quantity"]


def test_cannot_receive_twice(dbf):
    scan_once(db_name=dbf)
    order = db.get_restock_orders("Flagged", dbf)[0]
    db.receive_restock_order(order["id"], dbf)
    with pytest.raises(ValueError):
        db.receive_restock_order(order["id"], dbf)


def test_restocked_product_is_not_reflagged(dbf):
    scan_once(db_name=dbf)
    order = db.get_restock_orders("Flagged", dbf)[0]
    db.receive_restock_order(order["id"], dbf)
    report = scan_once(db_name=dbf)
    involved = ([p["id"] for p, _ in report["flagged"]]
                + [p["id"] for p in report["skipped"]])
    assert order["product_id"] not in involved


def test_cancelled_restock_can_be_reflagged(dbf):
    scan_once(db_name=dbf)
    order = db.get_restock_orders("Flagged", dbf)[0]
    db.cancel_restock_order(order["id"], dbf)
    report = scan_once(db_name=dbf)
    assert order["product_id"] in [p["id"] for p, _ in report["flagged"]]


def test_summary_reads_sensibly(dbf):
    assert "ordered restocks" in summarise_report(scan_once(db_name=dbf))
    assert "already on order" in summarise_report(scan_once(db_name=dbf))


# ========================================================= the two together
def test_an_order_can_trigger_a_restock(dbf):
    """Selling stock down should make the bot order more \u2014 the whole point."""
    healthy = [p for p in db.get_products(dbf)
               if p["stock"] > p["reorder_level"]][0]
    assert restock_quantity(healthy) == 0

    # Sell it down to below its reorder level.
    db.create_order("Big Buyer", healthy["id"],
                    healthy["stock"] - healthy["reorder_level"] + 1, dbf)

    report = scan_once(db_name=dbf)
    assert healthy["id"] in [p["id"] for p, _ in report["flagged"]]


def test_full_cycle_returns_stock_to_health(dbf):
    """Sell down -> bot flags -> restock received -> healthy again."""
    product = [p for p in db.get_products(dbf)
               if p["stock"] > p["reorder_level"]][0]
    db.create_order("Big Buyer", product["id"],
                    product["stock"] - 1, dbf)

    scan_once(db_name=dbf)
    order = [r for r in db.get_restock_orders("Flagged", dbf)
             if r["product_id"] == product["id"]][0]
    db.receive_restock_order(order["id"], dbf)

    after = db.get_product(product["id"], dbf)
    assert after["stock"] > after["reorder_level"]


def test_bot_scan_now_works_without_starting(dbf):
    bot = RestockBot(db_name=dbf)
    report = bot.scan_now()
    assert len(report["flagged"]) == 2
    assert bot.scans == 1
    assert not bot.running


def test_deleting_a_product_with_restocks_is_refused(dbf):
    scan_once(db_name=dbf)
    order = db.get_restock_orders(db_name=dbf)[0]
    with pytest.raises(db.InUseError):
        db.delete_product(order["product_id"], dbf)
