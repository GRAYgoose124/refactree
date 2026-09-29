"""A deliberately monolithic shop script: models, storage, pricing, reports and CLI in one file."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Iterable

__version__ = "1.2.0"

# --- configuration ---------------------------------------------------------
DB_PATH = ":memory:"
DEFAULT_CURRENCY = "USD"
CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
TAX_RATE = Decimal("0.08")
LOW_STOCK_THRESHOLD = 3
SKU_PATTERN = r"^[A-Z]{3}-\d{4}$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$"
TABLE_WIDTH = 60

logger = logging.getLogger("shop")


# --- money -----------------------------------------------------------------
def round_cents(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_money(text: str) -> Decimal:
    cleaned = text.strip().lstrip("".join(CURRENCY_SYMBOLS.values()))
    return round_cents(Decimal(cleaned))


def format_money(amount: Decimal, currency: str = DEFAULT_CURRENCY) -> str:
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{symbol}{round_cents(amount):,.2f}"


def sum_money(amounts: Iterable[Decimal]) -> Decimal:
    total = Decimal("0")
    for a in amounts:
        total += a
    return round_cents(total)


# --- validation ------------------------------------------------------------
class ValidationError(ValueError):
    """Raised when user supplied data is malformed."""


def validate_sku(sku: str) -> str:
    if not re.match(SKU_PATTERN, sku):
        raise ValidationError(f"bad sku: {sku!r}")
    return sku


def validate_email(email: str) -> str:
    if not re.match(EMAIL_PATTERN, email):
        raise ValidationError(f"bad email: {email!r}")
    return email.lower()


def validate_quantity(qty: int) -> int:
    if qty <= 0:
        raise ValidationError(f"quantity must be positive, got {qty}")
    return qty


# --- models ----------------------------------------------------------------
@dataclass
class Product:
    sku: str
    name: str
    price: Decimal
    stock: int = 0

    def __post_init__(self) -> None:
        validate_sku(self.sku)


@dataclass
class Customer:
    email: str
    name: str

    def __post_init__(self) -> None:
        self.email = validate_email(self.email)


@dataclass
class OrderLine:
    product: Product
    quantity: int

    @property
    def subtotal(self) -> Decimal:
        return round_cents(self.product.price * self.quantity)


_order_counter = 1000


def next_order_id() -> int:
    global _order_counter
    _order_counter += 1
    return _order_counter


@dataclass
class Order:
    customer: Customer
    lines: list[OrderLine] = field(default_factory=list)
    discount: Decimal = Decimal("0")
    order_id: int = field(default_factory=next_order_id)

    def add(self, product: Product, quantity: int) -> None:
        self.lines.append(OrderLine(product, validate_quantity(quantity)))

    @property
    def subtotal(self) -> Decimal:
        return sum_money(line.subtotal for line in self.lines)

    @property
    def tax(self) -> Decimal:
        return round_cents((self.subtotal - self.discount) * TAX_RATE)

    @property
    def total(self) -> Decimal:
        return round_cents(self.subtotal - self.discount + self.tax)


# --- discounts -------------------------------------------------------------
DISCOUNT_RULES: dict[str, type[DiscountRule]] = {}


def register_rule(cls: type[DiscountRule]) -> type[DiscountRule]:
    DISCOUNT_RULES[cls.code] = cls
    return cls


class DiscountRule:
    code = "base"

    def __init__(self, **params: str) -> None:
        self.params = params

    def amount(self, order: Order) -> Decimal:
        raise NotImplementedError


@register_rule
class PercentOff(DiscountRule):
    code = "percent"

    def amount(self, order: Order) -> Decimal:
        pct = Decimal(self.params.get("pct", "0")) / 100
        return round_cents(order.subtotal * pct)


@register_rule
class BuyXGetY(DiscountRule):
    code = "bxgy"

    def amount(self, order: Order) -> Decimal:
        sku = self.params["sku"]
        x, y = int(self.params.get("x", "2")), int(self.params.get("y", "1"))
        saved = Decimal("0")
        for line in order.lines:
            if line.product.sku == sku:
                free = (line.quantity // (x + y)) * y
                saved += line.product.price * free
        return round_cents(saved)


def build_rule(spec: str) -> DiscountRule:
    code, _, rest = spec.partition(":")
    params = dict(p.split("=", 1) for p in rest.split(",") if p)
    if code not in DISCOUNT_RULES:
        raise ValidationError(f"unknown discount {code!r}")
    return DISCOUNT_RULES[code](**params)


def apply_discounts(order: Order, rules: list[DiscountRule]) -> Decimal:
    best = max((r.amount(order) for r in rules), default=Decimal("0"))
    order.discount = min(best, order.subtotal)
    logger.debug("order %s discount %s", order.order_id, order.discount)
    return order.discount


# --- storage ---------------------------------------------------------------
SCHEMA = """
CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, price TEXT, stock INTEGER);
CREATE TABLE orders (id INTEGER PRIMARY KEY, email TEXT, total TEXT, payload TEXT);
"""


class Database:
    def __init__(self, path: str = DB_PATH) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def upsert_product(self, p: Product) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?)",
            (p.sku, p.name, str(p.price), p.stock),
        )

    def products(self) -> list[Product]:
        rows = self.conn.execute("SELECT sku, name, price, stock FROM products ORDER BY sku")
        return [Product(s, n, Decimal(pr), st) for s, n, pr, st in rows]

    def product(self, sku: str) -> Product:
        row = self.conn.execute(
            "SELECT sku, name, price, stock FROM products WHERE sku = ?", (sku,)
        ).fetchone()
        if row is None:
            raise KeyError(sku)
        return Product(row[0], row[1], Decimal(row[2]), row[3])

    def save_order(self, order: Order) -> None:
        payload = json.dumps(
            [{"sku": ln.product.sku, "qty": ln.quantity} for ln in order.lines]
        )
        self.conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?)",
            (order.order_id, order.customer.email, str(order.total), payload),
        )

    def orders(self) -> list[tuple[int, str, Decimal, list[dict[str, object]]]]:
        rows = self.conn.execute("SELECT id, email, total, payload FROM orders ORDER BY id")
        return [(i, e, Decimal(t), json.loads(p)) for i, e, t, p in rows]


# --- inventory -------------------------------------------------------------
class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self, db: Database) -> None:
        self.db = db

    def restock(self, sku: str, qty: int) -> Product:
        p = self.db.product(validate_sku(sku))
        p.stock += validate_quantity(qty)
        self.db.upsert_product(p)
        return p

    def reserve(self, sku: str, qty: int) -> Product:
        p = self.db.product(sku)
        if p.stock < qty:
            raise OutOfStock(f"{sku}: have {p.stock}, need {qty}")
        p.stock -= qty
        self.db.upsert_product(p)
        return p

    def low_stock(self) -> list[Product]:
        return [p for p in self.db.products() if p.stock <= LOW_STOCK_THRESHOLD]


def place_order(
    db: Database, inv: Inventory, customer: Customer, items: dict[str, int], rules: list[DiscountRule]
) -> Order:
    order = Order(customer)
    for sku, qty in items.items():
        order.add(inv.reserve(sku, qty), qty)
    apply_discounts(order, rules)
    db.save_order(order)
    logger.info("placed order %s total %s", order.order_id, order.total)
    return order


# --- reporting -------------------------------------------------------------
def pad(text: str, width: int, right: bool = False) -> str:
    return text.rjust(width) if right else text.ljust(width)


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    rule = "-" * min(TABLE_WIDTH, sum(widths) + 3 * (len(widths) - 1))
    out = [" | ".join(pad(h, w) for h, w in zip(headers, widths)), rule]
    for r in rows:
        out.append(" | ".join(pad(c, w, right=i > 0) for i, (c, w) in enumerate(zip(r, widths))))
    return "\n".join(out)


def inventory_report(inv: Inventory) -> str:
    rows = [[p.sku, p.name, format_money(p.price), str(p.stock)] for p in inv.db.products()]
    low = ", ".join(p.sku for p in inv.low_stock()) or "none"
    return render_table(["SKU", "Name", "Price", "Stock"], rows) + f"\nlow stock: {low}"


def sales_report(db: Database) -> str:
    by_customer: dict[str, list[Decimal]] = defaultdict(list)
    for _id, email, total, _payload in db.orders():
        by_customer[email].append(total)
    rows = [[e, str(len(t)), format_money(sum_money(t))] for e, t in sorted(by_customer.items())]
    grand = sum_money(t for ts in by_customer.values() for t in ts)
    return render_table(["Customer", "Orders", "Revenue"], rows) + f"\nTOTAL {format_money(grand)}"


# --- cli -------------------------------------------------------------------
SEED = [
    ("ABC-0001", "Widget", "9.99", 10),
    ("ABC-0002", "Gadget", "24.50", 4),
    ("XYZ-1000", "Doohickey", "3.25", 2),
]


def seed(db: Database) -> None:
    for sku, name, price, stock in SEED:
        db.upsert_product(Product(sku, name, parse_money(price), stock))


def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="shop")
    ap.add_argument("--discount", action="append", default=[])
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=__version__)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    db = Database()
    seed(db)
    inv = Inventory(db)
    rules = [build_rule(s) for s in args.discount]
    alice = Customer("Alice@Example.com", "Alice")
    bob = Customer("bob@example.org", "Bob")
    try:
        place_order(db, inv, alice, {"ABC-0001": 3, "XYZ-1000": 1}, rules)
        place_order(db, inv, bob, {"ABC-0002": 2}, rules)
        place_order(db, inv, bob, {"ABC-0002": 5}, rules)
    except OutOfStock as exc:
        print(f"warning: {exc}")
    inv.restock("XYZ-1000", 5)
    print(inventory_report(inv))
    print()
    print(sales_report(db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
