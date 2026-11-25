"""Register the CLIC page and menu action with the AB3 host."""

from importlib.resources import files

from activity_browser.plugins import ABAction, PluginContext, reveal_page
from qtpy import QtGui

from .page import ClicPage

PAGE_ID = "ab_clic.catalog"
OPEN_ACTION_ID = "ab_clic.open"


class OpenClicPage(ABAction):
    text = "Browse and import"

    @classmethod
    def get_QAction(cls, *args, **kwargs):
        action = super().get_QAction(*args, **kwargs)
        action.setIconVisibleInMenu(True)
        return action

    @staticmethod
    def run():
        reveal_page(PAGE_ID)


def activate(ctx: PluginContext) -> None:
    class CatalogPage(ClicPage):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, host=ctx, **kwargs)

    mark = files("ab_clic").joinpath("assets", "clic-mark.svg")
    pixmap = QtGui.QPixmap()
    pixmap.loadFromData(mark.read_bytes(), "SVG")
    OpenClicPage.icon = QtGui.QIcon(pixmap)
    ctx.register_page(PAGE_ID, CatalogPage, title="CLIC", show_by_default=False)
    ctx.register_action(OPEN_ACTION_ID, OpenClicPage)
    ctx.register_menu_item("Browse and import", OPEN_ACTION_ID)
