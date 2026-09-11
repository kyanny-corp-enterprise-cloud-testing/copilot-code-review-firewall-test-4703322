FREE_SHIPPING_MINIMUM = 5000


def qualifies_for_free_shipping(order_total):
    return order_total >= FREE_SHIPPING_MINIMUM