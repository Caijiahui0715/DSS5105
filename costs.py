"""What renting costs beyond the monthly rent, for the agent's estimate_costs tool.

Rules as published by IRAS and common Singapore practice, checked 2026-10-10:
- Stamp duty on a lease of up to 4 years is 0.4% of the total rent for the lease, rounded down to
  the dollar with a minimum of S$1; a longer lease pays on 4 years' rent. A lease whose average
  annual rent is S$1,000 or less is exempt. IRAS uses the higher of the contract and market rent.
- The security deposit is usually one month's rent for each year of the lease. The good-faith
  deposit paid with the letter of intent becomes this deposit at signing, so it is not extra.
- A tenant's agent usually charges half a month's rent for each year of the lease, plus 9% GST.
  This is practice, not regulation, and is negotiable.
"""

import math
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

STAMP_DUTY_RATE = Decimal("0.004")
STAMP_DUTY_EXEMPT_ANNUAL_RENT = 1000
STAMP_DUTY_MAX_MONTHS = 48
GST_RATE = Decimal("0.09")
AGENT_MONTHS_PER_YEAR = Decimal("0.5")


def lease_years(lease_months: int) -> int:
    """Whole years a lease spans for deposit and agent-fee rules: 6 months counts as 1, 18 as 2."""
    return max(1, math.ceil(lease_months / 12))


def lease_costs(
    rent: float,
    lease_months: int,
    *,
    deposit_months: int | None = None,
    agent: bool = False,
    agent_fee: float | None = None,
) -> dict:
    """Costs of one lease in SGD. deposit_months and agent_fee are what the user stated, if anything;
    a stated agent fee is taken as the full amount, without adding GST."""
    rent_d = _cents(Decimal(str(rent)))
    total_rent = rent_d * lease_months
    exempt = rent_d * 12 <= STAMP_DUTY_EXEMPT_ANNUAL_RENT
    duty_base = rent_d * min(lease_months, STAMP_DUTY_MAX_MONTHS)
    stamp_duty = Decimal(0) if exempt else max(Decimal(1), (duty_base * STAMP_DUTY_RATE).quantize(Decimal(1), ROUND_DOWN))
    deposit_stated = deposit_months is not None
    deposit_months = deposit_months if deposit_stated else lease_years(lease_months)
    deposit = rent_d * deposit_months
    fee = gst = None
    if agent:
        if agent_fee is not None:
            fee = _cents(Decimal(str(agent_fee)))
        else:
            fee = _cents(rent_d * AGENT_MONTHS_PER_YEAR * lease_years(lease_months))
            gst = _cents(fee * GST_RATE)
    agent_total = (fee or Decimal(0)) + (gst or Decimal(0))
    total_cost = total_rent + stamp_duty + agent_total
    return {
        "rent_monthly_sgd": _money(rent_d),
        "lease_months": lease_months,
        "total_rent_sgd": _money(total_rent),
        "stamp_duty_sgd": _money(stamp_duty),
        "stamp_duty_base_sgd": _money(duty_base),
        "stamp_duty_exempt": exempt,
        "deposit_months": deposit_months,
        "deposit_months_stated": deposit_stated,
        "deposit_sgd": _money(deposit),
        "agent_fee_sgd": _money(fee) if fee is not None else None,
        "agent_fee_stated": agent and agent_fee is not None,
        "agent_fee_gst_sgd": _money(gst) if gst is not None else None,
        "agent_fee_total_sgd": _money(agent_total) if agent else None,
        # Paid at signing: the deposit, the first month's rent in advance, stamp duty and any agent fee.
        "upfront_sgd": _money(deposit + rent_d + stamp_duty + agent_total),
        # Spent over the whole lease; the deposit comes back, so it is not counted.
        "total_cost_sgd": _money(total_cost),
        # For comparing leases of different lengths.
        "average_monthly_cost_sgd": _money(total_cost / lease_months),
    }


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), ROUND_HALF_UP)


def _money(value: Decimal) -> int | float:
    """Whole dollars as int, otherwise cents as float."""
    cents = value.quantize(Decimal("0.01"), ROUND_HALF_UP)
    return int(cents) if cents == cents.to_integral_value() else float(cents)
