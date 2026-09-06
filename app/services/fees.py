"""Platform take-rate math. Pure function, no I/O — computed and
snapshotted onto a Payment only at capture time (see app/routers/webhooks.py),
never at order-creation time, since an order that never gets paid earns the
platform nothing.
"""


def compute_platform_fee(*, amount_minor_units: int, take_rate_bps: int) -> tuple[int, int]:
    """Returns (platform_fee_minor_units, net_amount_minor_units).

    take_rate_bps is basis points (250 = 2.50%). Integer math throughout —
    amounts are always minor units (cents/paise), never floats.
    """
    fee = (amount_minor_units * take_rate_bps) // 10_000
    net = amount_minor_units - fee
    return fee, net
