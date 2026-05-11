from __future__ import annotations

from webui.components.alpaca_account import _visible_order_pages, render_orders_pagination


def test_visible_order_pages_keeps_latest_oldest_and_active_windows():
    assert _visible_order_pages(1, 5) == [1, 2, 3, 4, 5]
    assert _visible_order_pages(10, 20) == [1, 2, 3, 4, 5, "gap", 10, "gap", 16, 17, 18, 19, 20]


def test_render_orders_pagination_clamps_active_page_and_disables_current():
    component = render_orders_pagination(active_page=99, total_pages=3, total_orders=25, has_more=False, lang="en")

    assert component.className == "orders-pagination"
    buttons = component.children[0].children
    page_buttons = [button for button in buttons if getattr(button, "children", None) == "3"]
    assert page_buttons
    assert page_buttons[0].disabled is True
    assert "Page 3 of 3" in component.children[1].children

