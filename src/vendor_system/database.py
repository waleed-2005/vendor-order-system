"""
Vendor Order System - database layer.

This module began as the Week 4 Vendor Order backend and is carried into the
capstone unchanged in spirit: every SQL statement in the whole project still
lives here and nowhere else. It gains one new table, restock_orders, which is
where the automated restock bot records what it has flagged and ordered.

Every SQL statement in the whole project lives in this file. The Flask routes
and the Tkinter tool never build a query themselves, so there is exactly one
place where the data can be changed - and one place to check when something
looks wrong.

All queries are PARAMETERISED (the ? placeholders), which keeps user input as
data and makes SQL injection impossible.
"""

import os
import sqlite3
from datetime import datetime

# The database lives beside the user's data, not inside the installed package,
# so an installed copy never tries to write into site-packages.
DB_NAME = os.path.join(os.path.expanduser("~"), "vendor_system.db")

VALID_STATUSES = ("Pending", "Shipped", "Cancelled")


# --------------------------------------------------------------- exceptions
class OutOfStockError(Exception):
    """Raised when an order asks for more units than are in stock."""


class NotFoundError(Exception):
    """Raised when a product or order id does not exist."""


class InUseError(Exception):
    """Raised when a product cannot be deleted because orders reference it."""


# ---------------------------------------------------------------- plumbing
def get_connection(db_name=DB_NAME):
    conn = sqlite3.connect(db_name)
    conn.row_factory = sqlite3.Row          # rows behave like dictionaries
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_name=DB_NAME, seed=True):
    """Create the tables, and add sample data the first time only."""
    with get_connection(db_name) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL UNIQUE,
                stock         INTEGER NOT NULL DEFAULT 0,
                reorder_level INTEGER NOT NULL DEFAULT 5,
                price         REAL    NOT NULL DEFAULT 0.0
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                customer   TEXT    NOT NULL,
                product_id INTEGER NOT NULL,
                quantity   INTEGER NOT NULL,
                status     TEXT    NOT NULL DEFAULT 'Pending',
                created_at TEXT    NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id)
            )""")
        # NEW for the capstone: what the automated restock bot has flagged.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS restock_orders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  INTEGER NOT NULL,
                quantity    INTEGER NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'Flagged',
                created_at  TEXT    NOT NULL,
                source      TEXT    NOT NULL DEFAULT 'bot',
                FOREIGN KEY (product_id) REFERENCES products(id)
            )""")
        empty = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0

    if seed and empty:
        load_sample_data(db_name)


def load_sample_data(db_name=DB_NAME):
    """Wipe everything and load a realistic set of demo data.

    One product is deliberately below its reorder level so the low-stock
    alert has something to find straight away.
    """
    with get_connection(db_name) as conn:
        conn.execute("DELETE FROM restock_orders")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM sqlite_sequence"
                     " WHERE name IN ('orders','products','restock_orders')")
        conn.executemany(
            "INSERT INTO products (name, stock, reorder_level, price)"
            " VALUES (?, ?, ?, ?)",
            [("Blue Ballpoint Pen",  120, 30, 0.60),
             ("A4 Notebook",          45, 15, 2.40),
             ("Stapler",               4,  5, 4.75),    # LOW - below reorder
             ("Printer Paper (ream)", 18, 10, 6.20),
             ("Sticky Notes",          2,  8, 1.30)])   # LOW - below reorder
        conn.executemany(
            "INSERT INTO orders (customer, product_id, quantity, status, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [("Ahmed Traders", 1, 20, "Shipped",
              datetime.now().strftime("%Y-%m-%d %H:%M")),
             ("City Stationers", 2, 5, "Pending",
              datetime.now().strftime("%Y-%m-%d %H:%M"))])


def reset_database(db_name=DB_NAME):
    """Clear everything and reload the sample data (the Reset button)."""
    load_sample_data(db_name)


# ---------------------------------------------------------------- products
def add_product(name, stock, reorder_level=5, price=0.0, db_name=DB_NAME):
    """Create a product and return its new id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Product name cannot be empty")
    stock, reorder_level = int(stock), int(reorder_level)
    price = float(price)
    if stock < 0 or reorder_level < 0 or price < 0:
        raise ValueError("Stock, reorder level and price cannot be negative")

    with get_connection(db_name) as conn:
        try:
            cur = conn.execute(
                "INSERT INTO products (name, stock, reorder_level, price)"
                " VALUES (?, ?, ?, ?)", (name, stock, reorder_level, price))
        except sqlite3.IntegrityError:
            raise ValueError(f"A product named '{name}' already exists")
        return cur.lastrowid


def get_products(db_name=DB_NAME):
    with get_connection(db_name) as conn:
        return [dict(r) for r in
                conn.execute("SELECT * FROM products ORDER BY name").fetchall()]


def get_product(product_id, db_name=DB_NAME):
    with get_connection(db_name) as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?",
                           (product_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"No product with id {product_id}")
    return dict(row)


def update_stock(product_id, new_stock, db_name=DB_NAME):
    """Set a product's stock to an exact value (a restock or a correction)."""
    new_stock = int(new_stock)
    if new_stock < 0:
        raise ValueError("Stock cannot be negative")
    with get_connection(db_name) as conn:
        cur = conn.execute("UPDATE products SET stock = ? WHERE id = ?",
                           (new_stock, product_id))
    if cur.rowcount == 0:
        raise NotFoundError(f"No product with id {product_id}")
    return get_product(product_id, db_name)


def delete_product(product_id, db_name=DB_NAME):
    """Delete a product, refusing if any order still references it."""
    with get_connection(db_name) as conn:
        used = conn.execute("SELECT COUNT(*) FROM orders WHERE product_id = ?",
                            (product_id,)).fetchone()[0]
        used += conn.execute("SELECT COUNT(*) FROM restock_orders"
                             " WHERE product_id = ?", (product_id,)).fetchone()[0]
        if used:
            raise InUseError(
                f"Cannot delete: {used} order(s) still reference this product. "
                "Delete those orders first.")
        cur = conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    if cur.rowcount == 0:
        raise NotFoundError(f"No product with id {product_id}")
    return True


def low_stock_products(db_name=DB_NAME):
    """Products at or below their reorder level - what the alert tool watches."""
    with get_connection(db_name) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM products WHERE stock <= reorder_level"
            " ORDER BY stock ASC").fetchall()]


# ------------------------------------------------------------------ orders
def create_order(customer, product_id, quantity, db_name=DB_NAME):
    """Place an order and deduct the stock, refusing if there is not enough.

    The stock check and the deduction happen inside ONE transaction, so the
    stock level can never go negative even if two orders arrive together.
    """
    customer = (customer or "").strip()
    if not customer:
        raise ValueError("Customer name cannot be empty")
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")

    with get_connection(db_name) as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?",
                           (product_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No product with id {product_id}")
        if row["stock"] < quantity:
            raise OutOfStockError(
                f"Only {row['stock']} unit(s) of '{row['name']}' left, "
                f"but {quantity} were requested")

        conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?",
                     (quantity, product_id))
        cur = conn.execute(
            "INSERT INTO orders (customer, product_id, quantity, status, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (customer, product_id, quantity, "Pending",
             datetime.now().strftime("%Y-%m-%d %H:%M")))
        return cur.lastrowid


def get_orders(status=None, db_name=DB_NAME):
    """List orders joined to their product, with the line total calculated."""
    sql = ("SELECT o.id, o.customer, o.quantity, o.status, o.created_at,"
           " p.id AS product_id, p.name AS product, p.price,"
           " (o.quantity * p.price) AS total"
           " FROM orders o JOIN products p ON p.id = o.product_id")
    params = ()
    if status:
        sql += " WHERE o.status = ?"
        params = (status,)
    sql += " ORDER BY o.id DESC"
    with get_connection(db_name) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_order_status(order_id, status, db_name=DB_NAME):
    if status not in VALID_STATUSES:
        raise ValueError(f"Status must be one of {list(VALID_STATUSES)}")
    with get_connection(db_name) as conn:
        cur = conn.execute("UPDATE orders SET status = ? WHERE id = ?",
                           (status, order_id))
    if cur.rowcount == 0:
        raise NotFoundError(f"No order with id {order_id}")
    return True


def delete_order(order_id, restock=True, db_name=DB_NAME):
    """Delete an order, returning its units to stock by default."""
    with get_connection(db_name) as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?",
                           (order_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No order with id {order_id}")
        if restock:
            conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?",
                         (row["quantity"], row["product_id"]))
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    return True


# ------------------------------------------------------- restock orders (bot)
def open_restock_order(product_id, db_name=DB_NAME):
    """Return the product's outstanding restock order, or None.

    The bot uses this to avoid raising a second order for something it has
    already flagged and which has not yet arrived.
    """
    with get_connection(db_name) as conn:
        row = conn.execute(
            "SELECT * FROM restock_orders"
            " WHERE product_id = ? AND status = 'Flagged'"
            " ORDER BY id DESC LIMIT 1", (product_id,)).fetchone()
    return dict(row) if row else None


def create_restock_order(product_id, quantity, source="bot", db_name=DB_NAME):
    """Record that a product needs restocking."""
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError("Restock quantity must be greater than zero")
    with get_connection(db_name) as conn:
        row = conn.execute("SELECT id FROM products WHERE id = ?",
                           (product_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No product with id {product_id}")
        cur = conn.execute(
            "INSERT INTO restock_orders (product_id, quantity, status,"
            " created_at, source) VALUES (?, ?, 'Flagged', ?, ?)",
            (product_id, quantity,
             datetime.now().strftime("%Y-%m-%d %H:%M"), source))
        return cur.lastrowid


def get_restock_orders(status=None, db_name=DB_NAME):
    """List restock orders joined to their product."""
    sql = ("SELECT r.id, r.quantity, r.status, r.created_at, r.source,"
           " p.id AS product_id, p.name AS product, p.stock, p.reorder_level"
           " FROM restock_orders r JOIN products p ON p.id = r.product_id")
    params = ()
    if status:
        sql += " WHERE r.status = ?"
        params = (status,)
    sql += " ORDER BY r.id DESC"
    with get_connection(db_name) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def receive_restock_order(restock_id, db_name=DB_NAME):
    """Mark a restock order as received and ADD its units to stock.

    The stock increase and the status change happen in one transaction, so
    stock can never be credited twice for the same delivery.
    """
    with get_connection(db_name) as conn:
        row = conn.execute("SELECT * FROM restock_orders WHERE id = ?",
                           (restock_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"No restock order with id {restock_id}")
        if row["status"] == "Received":
            raise ValueError(f"Restock order {restock_id} was already received")
        conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?",
                     (row["quantity"], row["product_id"]))
        conn.execute("UPDATE restock_orders SET status = 'Received'"
                     " WHERE id = ?", (restock_id,))
    return True


def cancel_restock_order(restock_id, db_name=DB_NAME):
    with get_connection(db_name) as conn:
        cur = conn.execute("UPDATE restock_orders SET status = 'Cancelled'"
                           " WHERE id = ? AND status = 'Flagged'", (restock_id,))
    if cur.rowcount == 0:
        raise NotFoundError(
            f"No outstanding restock order with id {restock_id}")
    return True
