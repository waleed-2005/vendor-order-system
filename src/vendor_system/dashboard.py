"""
============================================================================
 Vendor Order System  \u2014  Dashboard
 ----------------------------------------------------------------------------
 Student  : Waleed Ahmad Khan
 Roll No  : Mtech-PY26017
 Concepts : Capstone Integration
 GUI      : Tkinter
 Level    : Advanced
============================================================================

 ONE dashboard covering the whole system:

   * Inventory   - the Week 4 vendor backend: products, stock, restocking
   * Orders      - place customer orders; stock is deducted automatically and
                   overselling is refused
   * Restock Bot - the Week 5 automation: scans on a schedule, auto-flags
                   anything at or below its reorder level, and raises a
                   restock order without being asked
   * Activity    - a live log of everything the bot has done, also written to
                   a file on disk

 Everything reads and writes through one packaged module (vendor_system), so
 the tabs can never disagree about stock.

 RUN:  python -m vendor_system.dashboard        (after pip install .)
   or: python run_dashboard.py                  (straight from the folder)
============================================================================
"""

import queue
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from . import database as db
from .restock_bot import (DEFAULT_INTERVAL, DEFAULT_TARGET_FACTOR, LOG_FILE,
                          RestockBot, scan_once, setup_logging,
                          summarise_report)

BG = "#f4f6f8"
INK = "#1f2933"


class DashboardApp(tk.Tk):

    def __init__(self, db_name=db.DB_NAME):
        super().__init__()
        self.db_name = db_name
        self.title("Vendor Order System  \u2014  Dashboard with Automated Restock "
                   "Bot  (Waleed Ahmad Khan)")
        self.geometry("1080x720")
        self.configure(bg=BG)

        setup_logging()
        db.init_db(self.db_name)

        # The bot runs on a background thread. Tkinter is not thread-safe, so
        # reports are put on a queue and the GUI drains it on its own timer.
        self.reports = queue.Queue()
        self.bot = RestockBot(interval=DEFAULT_INTERVAL,
                              target_factor=DEFAULT_TARGET_FACTOR,
                              on_report=self.reports.put,
                              db_name=self.db_name)

        self._style()
        self._build_ui()
        self.refresh_all()
        self.after(300, self._poll_reports)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------- style
    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")      # honours colours; macOS 'aqua' ignores them
        except tk.TclError:
            pass
        style.configure("Treeview", background="#ffffff",
                        fieldbackground="#ffffff", foreground=INK, rowheight=26)
        style.configure("Treeview.Heading", background="#e4e7eb",
                        foreground=INK, relief="flat")
        style.map("Treeview", background=[("selected", "#2b6cb0")],
                  foreground=[("selected", "#ffffff")])
        style.configure("TNotebook", background=BG)
        style.configure("TNotebook.Tab", padding=(16, 8))

    # --------------------------------------------------------------- layout
    def _build_ui(self):
        header = tk.Frame(self, bg="#1f2933", padx=16, pady=10)
        header.pack(fill="x")
        tk.Label(header, text="Vendor Order System", bg="#1f2933", fg="#ffffff",
                 font=("Helvetica", 15, "bold")).pack(side="left")
        tk.Label(header, text="Waleed Ahmad Khan  |  Mtech-PY26017",
                 bg="#1f2933", fg="#9aa5b1").pack(side="right")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=8)
        self._build_inventory_tab()
        self._build_orders_tab()
        self._build_bot_tab()

        self.status = tk.Label(self, text="Ready.", anchor="w", bd=1,
                               relief="sunken", padx=8, bg="#e4e7eb", fg=INK)
        self.status.pack(fill="x", side="bottom")

    # ------------------------------------------------------------ inventory
    def _build_inventory_tab(self):
        tab = tk.Frame(self.tabs, bg=BG)
        self.tabs.add(tab, text="  Inventory  ")

        form = tk.LabelFrame(tab, text="Add a product", bg=BG, fg=INK,
                             padx=10, pady=8)
        form.pack(fill="x", padx=8, pady=(8, 4))
        self.p_name = self._entry(form, "Name", 18)
        self.p_stock = self._entry(form, "Stock", 7)
        self.p_reorder = self._entry(form, "Reorder at", 7, "5")
        self.p_price = self._entry(form, "Price", 7, "0")
        tk.Button(form, text="Add product",
                  command=self.add_product).pack(side="left", padx=6)
        tk.Button(form, text="Restock selected",
                  command=self.restock_selected).pack(side="left", padx=3)
        tk.Button(form, text="Delete selected",
                  command=self.delete_product).pack(side="left", padx=3)
        tk.Button(form, text="Reset demo data",
                  command=self.reset_data).pack(side="right", padx=3)

        cols = ("id", "name", "stock", "reorder", "price", "status")
        self.inv = ttk.Treeview(tab, columns=cols, show="headings", height=14)
        for c, label, w, a in [("id", "#", 45, "center"), ("name", "Product", 300, "w"),
                               ("stock", "Stock", 90, "center"),
                               ("reorder", "Reorder at", 100, "center"),
                               ("price", "Price", 90, "center"),
                               ("status", "Status", 120, "center")]:
            self.inv.heading(c, text=label)
            self.inv.column(c, width=w, anchor=a)
        # Explicit text colours: without them dark mode draws white on pale.
        self.inv.tag_configure("low", background="#ffd6d6", foreground="#8a1c1c")
        self.inv.tag_configure("ok", background="#e3f6e8", foreground="#14501e")
        self.inv.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    # --------------------------------------------------------------- orders
    def _build_orders_tab(self):
        tab = tk.Frame(self.tabs, bg=BG)
        self.tabs.add(tab, text="  Orders  ")

        form = tk.LabelFrame(tab, text="Place a customer order", bg=BG, fg=INK,
                             padx=10, pady=8)
        form.pack(fill="x", padx=8, pady=(8, 4))
        self.o_customer = self._entry(form, "Customer", 18)
        tk.Label(form, text="Product", bg=BG, fg=INK).pack(side="left", padx=(8, 3))
        self.o_product = ttk.Combobox(form, width=28, state="readonly")
        self.o_product.pack(side="left", padx=3)
        self.o_qty = self._entry(form, "Qty", 6, "1")
        tk.Button(form, text="Place order",
                  command=self.place_order).pack(side="left", padx=6)
        tk.Button(form, text="Delete selected (returns stock)",
                  command=self.delete_order).pack(side="right", padx=3)

        cols = ("id", "customer", "product", "qty", "total", "status", "when")
        self.orders = ttk.Treeview(tab, columns=cols, show="headings", height=14)
        for c, label, w, a in [("id", "#", 45, "center"),
                               ("customer", "Customer", 190, "w"),
                               ("product", "Product", 220, "w"),
                               ("qty", "Qty", 70, "center"),
                               ("total", "Total", 90, "center"),
                               ("status", "Status", 100, "center"),
                               ("when", "Placed", 140, "center")]:
            self.orders.heading(c, text=label)
            self.orders.column(c, width=w, anchor=a)
        self.orders.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    # ------------------------------------------------------------- bot tab
    def _build_bot_tab(self):
        tab = tk.Frame(self.tabs, bg=BG)
        self.tabs.add(tab, text="  Restock Bot  ")

        panel = tk.LabelFrame(tab, text="Automation", bg=BG, fg=INK,
                              padx=10, pady=8)
        panel.pack(fill="x", padx=8, pady=(8, 4))

        tk.Label(panel, text="Scan every", bg=BG, fg=INK).pack(side="left")
        self.interval = tk.Spinbox(panel, from_=5, to=3600, width=6)
        self.interval.delete(0, "end")
        self.interval.insert(0, str(DEFAULT_INTERVAL))
        self.interval.pack(side="left", padx=4)
        tk.Label(panel, text="seconds   Top up to reorder \u00d7", bg=BG,
                 fg=INK).pack(side="left")
        self.factor = tk.Spinbox(panel, from_=1.0, to=10.0, increment=0.5,
                                 width=5, format="%.1f")
        self.factor.delete(0, "end")
        self.factor.insert(0, str(DEFAULT_TARGET_FACTOR))
        self.factor.pack(side="left", padx=4)

        self.bot_btn = tk.Button(panel, text="Start Bot", width=12,
                                 command=self.toggle_bot)
        self.bot_btn.pack(side="left", padx=(14, 4))
        tk.Button(panel, text="Scan Now", width=10,
                  command=self.scan_now).pack(side="left", padx=3)
        tk.Button(panel, text="Preview (no changes)", width=18,
                  command=self.preview).pack(side="left", padx=3)

        self.bot_state = tk.Label(tab, text="Bot is stopped.", anchor="w",
                                  bg="#eef1f5", fg=INK, padx=8, pady=6,
                                  relief="solid", bd=1)
        self.bot_state.pack(fill="x", padx=8, pady=4)

        mid = tk.Frame(tab, bg=BG)
        mid.pack(fill="both", expand=True, padx=8)

        left = tk.Frame(mid, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text="Restock orders raised by the bot", bg=BG,
                 fg=INK, anchor="w").pack(fill="x")
        cols = ("id", "product", "qty", "status", "when", "source")
        self.restocks = ttk.Treeview(left, columns=cols, show="headings", height=9)
        for c, label, w, a in [("id", "#", 45, "center"),
                               ("product", "Product", 200, "w"),
                               ("qty", "Qty", 70, "center"),
                               ("status", "Status", 100, "center"),
                               ("when", "Raised", 130, "center"),
                               ("source", "By", 70, "center")]:
            self.restocks.heading(c, text=label)
            self.restocks.column(c, width=w, anchor=a)
        self.restocks.tag_configure("flagged", background="#fff4e5",
                                    foreground="#8a5a00")
        self.restocks.tag_configure("received", background="#e3f6e8",
                                    foreground="#14501e")
        self.restocks.pack(fill="both", expand=True)

        btns = tk.Frame(left, bg=BG)
        btns.pack(fill="x", pady=4)
        tk.Button(btns, text="Mark as received (adds stock)",
                  command=self.receive_restock).pack(side="left")
        tk.Button(btns, text="Cancel",
                  command=self.cancel_restock).pack(side="left", padx=4)

        tk.Label(tab, text=f"Activity log  (also saved to {LOG_FILE})",
                 bg=BG, fg=INK, anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        self.log = tk.Text(tab, height=9, wrap="none", bd=0,
                           bg="#1f2933", fg="#e4e7eb", highlightthickness=0)
        self.log.pack(fill="x", padx=8, pady=(0, 8))

    # -------------------------------------------------------------- helpers
    def _entry(self, parent, label, width, default=""):
        tk.Label(parent, text=label, bg=BG, fg=INK).pack(side="left", padx=(8, 3))
        e = tk.Entry(parent, width=width)
        if default:
            e.insert(0, default)
        e.pack(side="left", padx=3)
        return e

    def log_line(self, text):
        self.log.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log.see("end")

    def selected_id(self, tree):
        sel = tree.selection()
        return int(tree.item(sel[0])["values"][0]) if sel else None

    # ------------------------------------------------------------- refresh
    def refresh_all(self):
        self.refresh_inventory()
        self.refresh_orders()
        self.refresh_restocks()

    def refresh_inventory(self):
        self.inv.delete(*self.inv.get_children())
        products = db.get_products(self.db_name)
        for p in products:
            low = p["stock"] <= p["reorder_level"]
            self.inv.insert("", "end", iid=str(p["id"]),
                            values=(p["id"], p["name"], p["stock"],
                                    p["reorder_level"], f"{p['price']:.2f}",
                                    "REORDER" if low else "OK"),
                            tags=("low" if low else "ok",))
        self.o_product["values"] = [f"{p['id']} - {p['name']} ({p['stock']} in stock)"
                                    for p in products]
        if products and not self.o_product.get():
            self.o_product.current(0)

    def refresh_orders(self):
        self.orders.delete(*self.orders.get_children())
        for o in db.get_orders(db_name=self.db_name):
            self.orders.insert("", "end", iid=str(o["id"]),
                               values=(o["id"], o["customer"], o["product"],
                                       o["quantity"], f"{o['total']:.2f}",
                                       o["status"], o["created_at"]))

    def refresh_restocks(self):
        self.restocks.delete(*self.restocks.get_children())
        for r in db.get_restock_orders(db_name=self.db_name):
            tag = ("flagged" if r["status"] == "Flagged"
                   else "received" if r["status"] == "Received" else "")
            self.restocks.insert("", "end", iid=str(r["id"]),
                                 values=(r["id"], r["product"], r["quantity"],
                                         r["status"], r["created_at"],
                                         r["source"]),
                                 tags=(tag,) if tag else ())

    # ----------------------------------------------------------- inventory
    def add_product(self):
        try:
            db.add_product(self.p_name.get(), self.p_stock.get() or 0,
                           self.p_reorder.get() or 5, self.p_price.get() or 0,
                           self.db_name)
        except (ValueError, TypeError) as e:
            messagebox.showwarning("Could not add product", str(e))
            return
        name = self.p_name.get()
        for e in (self.p_name, self.p_stock):
            e.delete(0, "end")
        self.refresh_all()
        self.status.config(text=f"Added {name}.")

    def restock_selected(self):
        pid = self.selected_id(self.inv)
        if pid is None:
            messagebox.showinfo("Nothing selected", "Click a product first.")
            return
        product = db.get_product(pid, self.db_name)
        answer = SimpleAsk(self, f"Restock {product['name']}",
                           f"Current stock: {product['stock']}\nNew stock level:",
                           str(product["stock"])).result
        if answer is None:
            return
        try:
            db.update_stock(pid, answer, self.db_name)
        except (ValueError, db.NotFoundError) as e:
            messagebox.showwarning("Could not update", str(e))
            return
        self.refresh_all()
        self.status.config(text=f"{product['name']} stock set to {answer}.")

    def delete_product(self):
        pid = self.selected_id(self.inv)
        if pid is None:
            messagebox.showinfo("Nothing selected", "Click a product first.")
            return
        try:
            db.delete_product(pid, self.db_name)
        except (db.NotFoundError, db.InUseError) as e:
            messagebox.showwarning("Could not delete", str(e))
            return
        self.refresh_all()
        self.status.config(text="Product deleted.")

    def reset_data(self):
        if not messagebox.askyesno("Reset demo data",
                                   "Clear everything and reload the sample set?"):
            return
        db.reset_database(self.db_name)
        self.refresh_all()
        self.log_line("Demo data reset.")
        self.status.config(text="Demo data reset.")

    # -------------------------------------------------------------- orders
    def place_order(self):
        choice = self.o_product.get()
        if not choice:
            messagebox.showwarning("No product", "Add a product first.")
            return
        product_id = int(choice.split(" - ")[0])
        try:
            db.create_order(self.o_customer.get(), product_id,
                            self.o_qty.get() or 0, self.db_name)
        except db.OutOfStockError as e:
            messagebox.showwarning("Order refused", str(e))
            self.status.config(text="Order refused - not enough stock.")
            return
        except (ValueError, TypeError, db.NotFoundError) as e:
            messagebox.showwarning("Could not place order", str(e))
            return
        self.o_customer.delete(0, "end")
        self.refresh_all()
        self.status.config(text="Order placed and stock updated.")

    def delete_order(self):
        oid = self.selected_id(self.orders)
        if oid is None:
            messagebox.showinfo("Nothing selected", "Click an order first.")
            return
        try:
            db.delete_order(oid, True, self.db_name)
        except db.NotFoundError as e:
            messagebox.showwarning("Could not delete", str(e))
            return
        self.refresh_all()
        self.status.config(text=f"Order {oid} deleted, stock returned.")

    # ----------------------------------------------------------------- bot
    def _bot_settings(self):
        try:
            interval = max(5, int(self.interval.get()))
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL
        try:
            factor = max(1.0, float(self.factor.get()))
        except (TypeError, ValueError):
            factor = DEFAULT_TARGET_FACTOR
        return interval, factor

    def toggle_bot(self):
        if self.bot.running:
            self.bot.stop()
            self.bot_btn.config(text="Start Bot")
            self.bot_state.config(text=f"Bot is stopped after {self.bot.scans} scan(s).")
            self.log_line("Bot stopped.")
            return
        interval, factor = self._bot_settings()
        self.bot.interval, self.bot.target_factor = interval, factor
        self.bot.start()
        self.bot_btn.config(text="Stop Bot")
        self.bot_state.config(text=f"Bot running \u2014 scanning every {interval}s, "
                                   f"topping up to reorder \u00d7 {factor:g}.")
        self.log_line(f"Bot started (every {interval}s, target factor {factor:g}).")

    def scan_now(self):
        _, factor = self._bot_settings()
        self.bot.target_factor = factor
        # The bot's on_report callback already puts the report on the queue,
        # so nothing is queued here - doing both would log the scan twice.
        self.bot.scan_now()

    def preview(self):
        """Show what WOULD be ordered, without changing anything."""
        _, factor = self._bot_settings()
        report = scan_once(factor, dry_run=True, db_name=self.db_name)
        if not report["flagged"] and not report["skipped"]:
            messagebox.showinfo("Preview",
                                f"All {report['checked']} product(s) are healthy \u2014 "
                                "nothing would be ordered.")
            return
        lines = [f"\u2022 {p['name']}: stock {p['stock']} \u2192 order {q}"
                 for p, q in report["flagged"]]
        skipped = [f"\u2022 {p['name']}: low, but already on order"
                   for p in report["skipped"]]
        messagebox.showinfo(
            "Preview \u2014 nothing has been changed",
            "The bot would raise these restock orders:\n\n"
            + ("\n".join(lines) if lines else "(none)")
            + ("\n\nSkipped:\n" + "\n".join(skipped) if skipped else ""))

    def _drain_reports(self):
        """Pull any reports the background bot has produced onto the screen.

        The bot runs on another thread, and Tkinter may only be touched from
        the main thread - so the report travels across on a queue and is
        applied here. This method only drains; the repeating timer is kept in
        _poll_reports, so calling this directly cannot start a second loop.
        """
        changed = False
        while True:
            try:
                report = self.reports.get_nowait()
            except queue.Empty:
                break
            changed = True
            self.log_line(summarise_report(report))
            for product, quantity in report["flagged"]:
                self.log_line(f"   FLAGGED {product['name']} "
                              f"(stock {product['stock']}) \u2192 ordered {quantity}")
            for problem in report["errors"]:
                self.log_line(f"   ERROR {problem}")
            self.status.config(text=summarise_report(report))
            if report["flagged"]:
                names = ", ".join(p["name"] for p, _ in report["flagged"])
                self.bot_state.config(
                    text=f"Last scan at {report['at']}: raised restock orders "
                         f"for {names}.")
            else:
                self.bot_state.config(
                    text=f"Last scan at {report['at']}: "
                         f"{report['checked']} product(s) checked, nothing new to order.")
        if changed:
            self.refresh_all()
        return changed

    def _poll_reports(self):
        """The repeating timer that keeps the screen up to date."""
        self._drain_reports()
        self.after(300, self._poll_reports)

    def receive_restock(self):
        rid = self.selected_id(self.restocks)
        if rid is None:
            messagebox.showinfo("Nothing selected", "Click a restock order first.")
            return
        try:
            db.receive_restock_order(rid, self.db_name)
        except (ValueError, db.NotFoundError) as e:
            messagebox.showwarning("Could not receive", str(e))
            return
        self.refresh_all()
        self.log_line(f"Restock order {rid} received \u2014 stock added.")
        self.status.config(text=f"Restock order {rid} received.")

    def cancel_restock(self):
        rid = self.selected_id(self.restocks)
        if rid is None:
            messagebox.showinfo("Nothing selected", "Click a restock order first.")
            return
        try:
            db.cancel_restock_order(rid, self.db_name)
        except db.NotFoundError as e:
            messagebox.showwarning("Could not cancel", str(e))
            return
        self.refresh_all()
        self.log_line(f"Restock order {rid} cancelled.")

    # ------------------------------------------------------------- shutdown
    def on_close(self):
        self.bot.stop()
        self.destroy()


class SimpleAsk(tk.Toplevel):
    """A small number-entry dialog that refuses invalid input."""

    def __init__(self, parent, title, prompt, default=""):
        super().__init__(parent)
        self.title(title)
        self.result = None
        self.transient(parent)
        self.grab_set()
        tk.Label(self, text=prompt, justify="left").pack(padx=20, pady=(14, 6))
        self.entry = tk.Entry(self, width=12, justify="center")
        self.entry.insert(0, default)
        self.entry.select_range(0, "end")
        self.entry.pack(pady=4)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda _e: self.ok())
        tk.Button(self, text="OK", command=self.ok).pack(pady=(8, 14))
        self.wait_window(self)

    def ok(self):
        raw = self.entry.get().strip()
        try:
            value = int(raw)
            if value < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid number",
                                 f"'{raw}' is not a valid amount.", parent=self)
            return
        self.result = value
        self.destroy()


def main():
    DashboardApp().mainloop()


if __name__ == "__main__":
    main()
