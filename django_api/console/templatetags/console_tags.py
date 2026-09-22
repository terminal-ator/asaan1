from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def rupees(value):
    try:
        return f"{(Decimal(value) / Decimal('100')):,.2f}"
    except (TypeError, ValueError, ArithmeticError):
        return "0.00"
