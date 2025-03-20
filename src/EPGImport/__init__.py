#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import absolute_import
from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from gettext import bindtextdomain, dgettext, gettext
from os.path import exists
from os import environ


PluginLanguageDomain = "EPGImport"
PluginLanguagePath = "Extensions/EPGImport/locale"


isDreambox = False
if exists("/usr/bin/apt-get"):
	isDreambox = True


def localeInit():
	if isDreambox:
		lang = language.getLanguage()[:2]
		environ["LANGUAGE"] = lang
	bindtextdomain(PluginLanguageDomain, resolveFilename(SCOPE_PLUGINS, PluginLanguagePath))


if isDreambox:
	def _(txt):
		return dgettext(PluginLanguageDomain, txt) if txt else ""
else:
	def _(txt):
		translated = dgettext(PluginLanguageDomain, txt)
		if translated:
			return translated
		else:
			print(("[%s] fallback to default translation for %s" % (PluginLanguageDomain, txt)))
			return gettext(txt)

localeInit()
language.addCallback(localeInit)
