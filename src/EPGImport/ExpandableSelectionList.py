#!/usr/bin/python
# -*- coding: utf-8 -*-

from Components.MenuList import MenuList
from Tools.Directories import resolveFilename, SCOPE_CURRENT_SKIN
from enigma import eListboxPythonMultiContent, gFont, RT_HALIGN_LEFT
from Tools.LoadPixmap import LoadPixmap
from enigma import getDesktop
import skin
import os

FHD = False

if getDesktop(0).size().width() == 1920:
    FHD = True


if os.path.exists("/var/lib/opkg/status"):
    expandableIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/expandable.png"))
    expandedIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/expanded.png"))
else:
    expandableIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/expandable.png"))
    expandedIcon = LoadPixmap(resolveFilename(SCOPE_CURRENT_SKIN, "icons/expanded.png"))


def loadSettings():
    global cat_desc_loc, entry_desc_loc, cat_icon_loc, entry_icon_loc
    if os.path.exists("/var/lib/opkg/status"):
        x, y, w, h = skin.parameters.get("SelectionListDescr", (25, 3, 650, 30))
    else:
        if FHD:
            x, y, w, h = (30, 9, 1200, 50)
        else:
            x, y, w, h = (20, 3, 800, 30)
    ind = x  # Indent the entries by the same amount as the icon.
    cat_desc_loc = (x, y, w, h)
    entry_desc_loc = (x + ind, y, w - ind, h)
    if os.path.exists("/var/lib/opkg/status"):
        x, y, w, h = skin.parameters.get("SelectionListLock", (0, 2, 25, 24))
    else:
        if FHD:
            x, y, w, h = (-25, 5, 40, 40)
        else:
            x, y, w, h = (-15, 2, 25, 25)
    cat_icon_loc = (x, 0, w, y + y + h)  # The category icon is larger
    entry_icon_loc = (x + ind, y, w, h)


def category(description, isExpanded=False):
    global cat_desc_loc, cat_icon_loc
    if isExpanded:
        icon = expandedIcon
    else:
        icon = expandableIcon
    return [
        (description, isExpanded, []),
        (eListboxPythonMultiContent.TYPE_TEXT,) + cat_desc_loc + (0, RT_HALIGN_LEFT, description),
        (eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,) + cat_icon_loc + (icon,)
    ]


def entry(description, value, selected):
    global entry_desc_loc, entry_icon_loc
    res = [
        (description, value, selected),
        (eListboxPythonMultiContent.TYPE_TEXT,) + entry_desc_loc + (0, RT_HALIGN_LEFT, description)
    ]
    if selected:
        if os.path.exists("/var/lib/opkg/status"):
            selectionpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "icons/lock_on.png"))
        else:
            selectionpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/icons/lock_on.png"))
    else:
        if os.path.exists("/var/lib/opkg/status"):
            selectionpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "icons/lock_off.png"))
        else:
            selectionpng = LoadPixmap(cached=True, path=resolveFilename(SCOPE_CURRENT_SKIN, "skin_default/icons/lock_off.png"))
    res.append((eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,) + entry_icon_loc + (selectionpng,))
    return res


def expand(cat, value=True):
    # cat is a list of data and icons
    if cat[0][1] != value:
        if os.path.exists("/var/lib/opkg/status"):
            ix, iy, iw, ih = skin.parameters.get("SelectionListLock", (0, 2, 25, 24))
        else:
            if FHD:
                ix, iy, iw, ih = (10, 5, 40, 40)
            else:
                ix, iy, iw, ih = (10, 2, 25, 25)
        if value:
            icon = expandedIcon
        else:
            icon = expandableIcon
        t = cat[0]
        cat[0] = (t[0], value, t[2])
        cat[2] = (eListboxPythonMultiContent.TYPE_PIXMAP_ALPHATEST,) + cat_icon_loc + (icon,)


def isExpanded(cat):
    return cat[0][1]


def isCategory(item):
    # Return whether list enty is a Category
    return hasattr(item[0][2], 'append')


class ExpandableSelectionList(MenuList):
    def __init__(self, tree=None, enableWrapAround=False):
        'tree is expected to be a list of categories'
        MenuList.__init__(self, [], enableWrapAround, content=eListboxPythonMultiContent)
        if os.path.exists("/var/lib/opkg/status"):
            font = skin.fonts.get("SelectionList", ("Regular", 20, 30))
        else:
            if FHD:
                font = ("Regular", 28, 50)
            else:
                font = ("Regular", 20, 30)
        self.l.setFont(0, gFont(font[0], font[1]))
        self.l.setItemHeight(font[2])
        self.tree = tree or []
        self.updateFlatList()

    def updateFlatList(self):
        # Update the view of the items by flattening the tree
        lc = []
        for cat in self.tree:
            lc.append(cat)
            if isExpanded(cat):
                for item in cat[0][2]:
                    lc.append(entry(*item))
        self.setList(lc)

    def toggleSelection(self):
        idx = self.getSelectedIndex()
        item = self.list[idx]
        # Only toggle selections, not expandables...
        if isCategory(item):
            expand(item, not item[0][1])
            self.updateFlatList()
        else:
            # Multiple items may have the same key. Toggle them all,
            # in both the visual list and the hidden items
            i = item[0]
            key = i[1]
            sel = not i[2]
            for idx, e in enumerate(self.list):
                if e[0][1] == key:
                    self.list[idx] = entry(e[0][0], key, sel)
            for cat in self.tree:
                for idx, e in enumerate(cat[0][2]):
                    if e[1] == key and e[2] != sel:
                        cat[0][2][idx] = (e[0], e[1], sel)
            self.setList(self.list)

    def enumSelected(self):
        for cat in self.tree:
            for entry in cat[0][2]:
                if entry[2]:
                    yield entry


loadSettings()
