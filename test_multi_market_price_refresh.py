from __future__ import annotations

import unittest

from multi_market_price_refresh import continue_shopping_if_prompted


class FakeLocator:
    def __init__(self, *, count: int = 0, text: str = "", on_click=None) -> None:
        self._count = count
        self._text = text
        self._on_click = on_click

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return self._count

    async def inner_text(self, timeout: int) -> str:
        return self._text

    async def click(self, timeout: int) -> None:
        if self._on_click:
            self._on_click()


class FakePage:
    def __init__(self, body: str, prompt: str) -> None:
        self.body = body
        self.prompt = prompt
        self.clicked = False

    def locator(self, selector: str) -> FakeLocator:
        if selector == "body":
            return FakeLocator(count=1, text=self.body)
        return FakeLocator()

    def get_by_role(self, role: str, name: str, exact: bool) -> FakeLocator:
        if role == "button" and name == self.prompt:
            return FakeLocator(count=1, on_click=lambda: setattr(self, "clicked", True))
        return FakeLocator()

    async def wait_for_load_state(self, state: str, timeout: int) -> None:
        return None

    async def wait_for_timeout(self, timeout: int) -> None:
        return None


class ContinueShoppingPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_handles_german_weiter_shoppen_interstitial(self) -> None:
        page = FakePage(
            "Klicke auf die Schaltfläche unten, um mit dem Einkauf fortzufahren Weiter shoppen",
            "Weiter shoppen",
        )

        handled = await continue_shopping_if_prompted(page)

        self.assertTrue(handled)
        self.assertTrue(page.clicked)

    async def test_ignores_regular_product_page(self) -> None:
        page = FakePage("Produktinformationen " * 200, "Weiter shoppen")

        handled = await continue_shopping_if_prompted(page)

        self.assertFalse(handled)
        self.assertFalse(page.clicked)


if __name__ == "__main__":
    unittest.main()
