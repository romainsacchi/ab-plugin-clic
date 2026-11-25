"""Register the CLIC page and menu action with the AB3 host."""

from activity_browser.plugins import ABAction, PluginContext, reveal_page

from .page import ClicPage

PAGE_ID = "ab_clic.catalog"
OPEN_ACTION_ID = "ab_clic.open"


class OpenClicPage(ABAction):
    text = "Browse and import"

    @staticmethod
    def run():
        reveal_page(PAGE_ID)


def activate(ctx: PluginContext) -> None:
    class CatalogPage(ClicPage):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, host=ctx, **kwargs)

    ctx.register_page(PAGE_ID, CatalogPage, title="CLIC", show_by_default=False)
    ctx.register_action(OPEN_ACTION_ID, OpenClicPage)
    ctx.register_menu_item("Browse and import", OPEN_ACTION_ID)
