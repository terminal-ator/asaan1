"""Which trade scheme applies to a product, and what it does to a line total.

A product can carry its own scheme % and also belong to group schemes. Schemes
do not stack: the shop gets the single best percentage that is running today.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from .models import Scheme


def running_schemes(on=None):
    on = on or timezone.localdate()
    return Scheme.objects.filter(
        Q(starts_on__isnull=True) | Q(starts_on__lte=on),
        Q(ends_on__isnull=True) | Q(ends_on__gte=on),
        active=True,
    )


def effective_schemes(products, on=None):
    """Map each product id to its best (percent, scheme name) for the day.

    The name is blank when the product's own scheme % is the best one.
    """
    products = list(products)
    best = {product.id: (product.scheme_percent, "") for product in products}
    through = Scheme.products.through
    rows = through.objects.filter(
        scheme__in=running_schemes(on), product_id__in=best.keys()
    ).values_list("product_id", "scheme__percent", "scheme__name")
    for product_id, percent, name in rows:
        if percent > best[product_id][0]:
            best[product_id] = (percent, name)
    return best


def discounted_total(quantity, rate, percent):
    """Taxable value of a line after the scheme, in paise."""
    gross = Decimal(quantity) * Decimal(rate)
    return int((gross * (100 - Decimal(percent)) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
