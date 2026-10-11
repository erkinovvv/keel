"""Simulated brokerage account used for permissioned M2 order flows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Iterable

from .allocation import Allocation
from .catalog import Product
from .compliance import pretrade_check
from .profiling import InvestorProfile


@dataclass
class SimulatedOrder:
    order_id: str
    product_id: str
    amount: float
    risk_class: int
    status: str = "DRAFT"
    created_on: date = field(default_factory=date.today)
    settles_on: date | None = None
    cooling_off_until: date | None = None

    def summary(self) -> str:
        return f"{self.order_id}|BUY|{self.product_id}|{self.amount:.8f}|R{self.risk_class}"

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["created_on"] = self.created_on.isoformat()
        result["settles_on"] = self.settles_on.isoformat() if self.settles_on else None
        result["cooling_off_until"] = self.cooling_off_until.isoformat() if self.cooling_off_until else None
        return result


@dataclass
class SimulatedAccount:
    cash: float = 1_000_000.0
    holdings: dict[str, float] = field(default_factory=dict)
    orders: dict[str, SimulatedOrder] = field(default_factory=dict)

    def create_draft_orders(
        self,
        allocation: Allocation,
        products: Iterable[Product],
        profile: InvestorProfile,
        *,
        max_order_amount: float,
        max_daily_order_amount: float,
        max_orders_per_session: int,
        cooling_off_days: int,
    ) -> list[SimulatedOrder]:
        """Create BUY drafts only after deterministic suitability and limit checks."""

        allowed, reasons = pretrade_check(profile, allocation, products, self.cash)
        if not allowed:
            raise ValueError(f"pre-trade checks failed: {', '.join(reasons)}")
        if len(self.orders) + len(allocation.holdings) > max_orders_per_session:
            raise ValueError("maximum orders per session exceeded")
        today_total = sum(order.amount for order in self.orders.values() if order.created_on == date.today() and order.status != "CANCELLED")
        new_total = sum(holding.amount for holding in allocation.holdings)
        if today_total + new_total > max_daily_order_amount:
            raise ValueError("daily order amount cap exceeded")
        if any(holding.amount > max_order_amount for holding in allocation.holdings):
            raise ValueError("per-order amount cap exceeded")
        by_id = {product.id: product for product in products}
        created: list[SimulatedOrder] = []
        for index, holding in enumerate(allocation.holdings, start=len(self.orders) + 1):
            product = by_id[holding.product_id]
            order = SimulatedOrder(
                order_id=f"order-{index}",
                product_id=holding.product_id,
                amount=holding.amount,
                risk_class=product.risk_class,
                cooling_off_until=date.today() + timedelta(days=cooling_off_days) if product.risk_class >= 4 else None,
            )
            self.orders[order.order_id] = order
            created.append(order)
        return created

    def execute(self, order_id: str) -> SimulatedOrder:
        """Execute a previously drafted order and apply T+2 settlement metadata."""

        try:
            order = self.orders[order_id]
        except KeyError as exc:
            raise ValueError("order not found") from exc
        if order.status != "DRAFT":
            raise ValueError("order is not executable")
        if order.cooling_off_until and date.today() < order.cooling_off_until:
            raise ValueError("cooling-off period is active for this product")
        if order.amount > self.cash:
            raise ValueError("insufficient simulated cash")
        self.cash -= order.amount
        self.holdings[order.product_id] = self.holdings.get(order.product_id, 0.0) + order.amount
        order.status = "EXECUTED"
        order.settles_on = date.today() + timedelta(days=2)
        return order

