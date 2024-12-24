#!/usr/bin/python
# -*- coding: utf-8 -*-

from . import _, isDreambox
from . import log
from . import ExpandableSelectionList
from . import EPGImport
from . import EPGConfig
from . import filtersServices

from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
# from Components.ScrollLabel import ScrollLabel
from Components.config import config, ConfigEnableDisable, ConfigSubsection, \
	ConfigYesNo, ConfigClock, getConfigListEntry, ConfigText, \
	ConfigSelection, ConfigNumber, ConfigSubDict, NoSave, configfile, ConfigDirectory
from Plugins.Plugin import PluginDescriptor
from Screens.ChoiceBox import ChoiceBox
from Screens.LocationBox import LocationBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from ServiceReference import ServiceReference
from Tools import Notifications
from Tools.Directories import SCOPE_PLUGINS, fileExists, resolveFilename
from Tools.FuzzyDate import FuzzyTime
from enigma import eEPGCache, eDVBDB, getDesktop, eTimer, eServiceCenter, eServiceReference
from enigma import eConsoleAppContainer
from sqlite3 import dbapi2 as sqlite
import Components.PluginComponent
import Screens.Standby
import os
import time


try:
	from Tools.StbHardware import getFPWasTimerWakeup
except:
	from Tools.DreamboxHardware import getFPWasTimerWakeup


def lastMACbyte():
	try:
		return int(open('/sys/class/net/eth0/address').readline().strip()[-2:], 16)
	except:
		return 256


def calcDefaultStarttime():
	try:
		# Use the last MAC byte as time offset (half-minute intervals)
		offset = lastMACbyte() * 30
	except:
		offset = 7680
	return (5 * 60 * 60) + offset


def getMountPoints():
	mount_points = []
	try:
		with open('/proc/mounts', 'r') as mounts:
			for line in mounts:
				parts = line.split()
				mount_point = parts[1]
				if os.path.ismount(mount_point) and os.access(mount_point, os.W_OK):
					mount_points.append(mount_point)
	except Exception as e:
		print("[EPGImport] Error reading /proc/mounts:", e)
	return mount_points


mount_points = getMountPoints()
mount_point = None
for mp in mount_points:
	epg_path = os.path.join(mp, 'epg.dat')
	if os.path.exists(epg_path):
		mount_point = epg_path
		break


# HDD_EPG_DAT = mount_point or '/etc/enigma2/epg.dat'
HDD_EPG_DAT = '/etc/enigma2/epg.dat'
if config.misc.epgcache_filename.value:
	HDD_EPG_DAT = config.misc.epgcache_filename.value
else:
	config.misc.epgcache_filename.setValue(HDD_EPG_DAT)

# Set default configuration
config.plugins.epgimport = ConfigSubsection()
config.plugins.epgimport.enabled = ConfigEnableDisable(default=True)
config.plugins.epgimport.runboot = ConfigSelection(default="4", choices=[
	("1", _("always")),
	("2", _("only manual boot")),
	("3", _("only automatic boot")),
	("4", _("never"))
])
config.plugins.epgimport.runboot_restart = ConfigYesNo(default=False)
config.plugins.epgimport.runboot_day = ConfigYesNo(default=False)
config.plugins.epgimport.wakeup = ConfigClock(default=calcDefaultStarttime())
config.plugins.epgimport.showinplugins = ConfigYesNo(default=True)
config.plugins.epgimport.showinextensions = ConfigYesNo(default=True)
config.plugins.epgimport.deepstandby = ConfigSelection(default="skip", choices=[
	("wakeup", _("wake up and import")),
	("skip", _("skip the import"))
])

config.plugins.epgimport.pathdb = ConfigDirectory(default='/etc/enigma2/epg.dat')
# config.plugins.epgimport.pathdb = ConfigText(default=HDD_EPG_DAT)
config.plugins.epgimport.standby_afterwakeup = ConfigYesNo(default=False)
config.plugins.epgimport.shutdown = ConfigYesNo(default=False)
config.plugins.epgimport.longDescDays = ConfigNumber(default=5)
config.plugins.epgimport.showinmainmenu = ConfigYesNo(default=False)
config.plugins.epgimport.deepstandby_afterimport = NoSave(ConfigYesNo(default=False))
config.plugins.epgimport.parse_autotimer = ConfigYesNo(default=False)
config.plugins.epgimport.import_onlybouquet = ConfigYesNo(default=False)
config.plugins.epgimport.import_onlyiptv = ConfigYesNo(default=False)
config.plugins.epgimport.clear_oldepg = ConfigYesNo(default=False)
config.plugins.epgimport.day_profile = ConfigSelection(choices=[("1", _("Press OK"))], default="1")

config.plugins.extra_epgimport = ConfigSubsection()
config.plugins.extra_epgimport.last_import = ConfigText(default="0")
config.plugins.extra_epgimport.day_import = ConfigSubDict()
for i in range(7):
	config.plugins.extra_epgimport.day_import[i] = ConfigEnableDisable(default=True)

weekdays = [
	_("Monday"),
	_("Tuesday"),
	_("Wednesday"),
	_("Thursday"),
	_("Friday"),
	_("Saturday"),
	_("Sunday"),
]

# historically located (not a problem, we want to update it)
CONFIG_PATH = '/etc/epgimport'

# Global variable
autoStartTimer = None
_session = None
BouquetChannelListList = None
serviceIgnoreList = None
filterCounter = 0
isFilterRunning = 0


def getAlternatives(service):
	if not service:
		return None
	alternativeServices = eServiceCenter.getInstance().list(service)
	return alternativeServices and alternativeServices.getContent("S", True)


def getBouquetChannelList():
	channels = []
	global isFilterRunning, filterCounter
	isFilterRunning = 1
	serviceHandler = eServiceCenter.getInstance()
	mask = (eServiceReference.isMarker | eServiceReference.isDirectory)
	altrernative = eServiceReference.isGroup
	if config.usage.multibouquet.value:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "bouquets.tv" ORDER BY bouquet'
		bouquet_root = eServiceReference(bouquet_rootstr)
		list = serviceHandler.list(bouquet_root)
		if list:
			while True:
				s = list.getNext()
				if not s.valid():
					break
				if s.flags & eServiceReference.isDirectory:
					info = serviceHandler.info(s)
					if info:
						clist = serviceHandler.list(s)
						if clist:
							while True:
								service = clist.getNext()
								filterCounter += 1
								if not service.valid():
									break
								if not (service.flags & mask):
									if service.flags & altrernative:
										altrernative_list = getAlternatives(service)
										if altrernative_list:
											for channel in altrernative_list:
												refstr = ':'.join(channel.split(':')[:11])
												if refstr not in channels:
													channels.append(refstr)
									else:
										refstr = ':'.join(service.toString().split(':')[:11])
										if refstr not in channels:
											channels.append(refstr)
	else:
		bouquet_rootstr = '1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.favourites.tv" ORDER BY bouquet'
		bouquet_root = eServiceReference(bouquet_rootstr)
		services = serviceHandler.list(bouquet_root)
		if services is not None:
			while True:
				service = services.getNext()
				filterCounter += 1
				if not service.valid():
					break
				if not (service.flags & mask):
					if service.flags & altrernative:
						altrernative_list = getAlternatives(service)
						if altrernative_list:
							for channel in altrernative_list:
								refstr = ':'.join(channel.split(':')[:11])
								if refstr not in channels:
									channels.append(refstr)
					else:
						refstr = ':'.join(service.toString().split(':')[:11])
						if refstr not in channels:
							channels.append(refstr)
	isFilterRunning = 0
	return channels


def channelFilter(ref):
	if not ref:
		return False
	# ignore non IPTV
	if config.plugins.epgimport.import_onlyiptv.value and ("%3a//" not in ref.lower() or ref.startswith("1")):
		return False
	strref = str(ref)
	# channel = ServiceReference(strref).getServiceName()
	ssid = strref.split(":")
	if int(ssid[0]) == 1 and (int(ssid[6], 16) & 0xFFFF0000) == 0xEEEE0000:
		# convert hex stuff to integer
		sid = int(ssid[3], 16)
		tsid = int(ssid[4], 16)
		onid = int(ssid[5], 16)
		dvbnamespace = int(ssid[6], 16)
		if dvbnamespace > 2147483647:
			dvbnamespace -= 4294967296
		dvbnamespace_mask = int('FFFF0000', 16)
		if dvbnamespace_mask > 2147483647:
			dvbnamespace_mask -= 4294967296
		searchedserv = eDVBDB.getInstance().searchReference(tsid, onid, sid, dvbnamespace, dvbnamespace_mask)
		channel = ServiceReference(searchedserv).getServiceName()
	else:
		channel = ServiceReference(strref).getServiceName()
	if len(channel) > 0:
		print("[EPGimport] found channel %s %s" % (channel, strref))
		return True
	if config.plugins.epgimport.import_onlybouquet.value:
		return False
	else:
		return True


epgimport = EPGImport.EPGImport(eEPGCache.getInstance(), channelFilter)

lastImportResult = None


def startImport():
	if not epgimport.isImportRunning():
		HDD_EPG_DAT = config.misc.epgcache_filename.value
		if config.plugins.epgimport.clear_oldepg.value and hasattr(epgimport.epgcache, 'flushEPG'):
			EPGImport.unlink_if_exists(HDD_EPG_DAT)
			EPGImport.unlink_if_exists(HDD_EPG_DAT + '.backup')
			epgimport.epgcache.flushEPG()
		epgimport.onDone = doneImport
		epgimport.beginImport(longDescUntil=config.plugins.epgimport.longDescDays.value * 24 * 3600 + time.time())
	else:
		log.write("[EPGImport] AutoTimer Plugin not installed")


"""
# def startImport():
	# if not epgimport.isImportRunning():
		# EPGImport.HDD_EPG_DAT = config.misc.epgcache_filename.value
		# if config.plugins.epgimport.clear_oldepg.value and hasattr(epgimport.epgcache, 'flushEPG'):
			# EPGImport.unlink_if_exists(EPGImport.HDD_EPG_DAT)
			# EPGImport.unlink_if_exists(EPGImport.HDD_EPG_DAT + '.backup')
			# epgimport.epgcache.flushEPG()
		# epgimport.onDone = doneImport
		# epgimport.beginImport(longDescUntil=config.plugins.epgimport.longDescDays.value * 24 * 3600 + time.time())
	# else:
		# log.write("[EPGImport] AutoTimer Plugin not installed")
"""


##################################
# Configuration GUI
sz_w = getDesktop(0).size().width()


class EPGImportConfig(ConfigListScreen, Screen):
	if sz_w >= 1920:
		skin = """
			<screen position="center,center" size="1200,820" title="EPG Import Configuration">
				<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/green.png" position="305,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/yellow.png" position="600,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/blue.png" position="895,5" size="295,70" />
				<widget backgroundColor="#9f1313" font="Regular;30" halign="center" name="key_red" position="10,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#1f771f" font="Regular;30" halign="center" name="key_green" position="305,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#a08500" font="Regular;30" halign="center" name="key_yellow" position="600,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#18188b" font="Regular;30" halign="center" name="key_blue" position="895,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<eLabel backgroundColor="grey" position="10,80" size="1180,1" />
				<widget enableWrapAround="1" name="config" position="10,90" scrollbarMode="showOnDemand" size="1180,538" />
				<eLabel backgroundColor="grey" position="10,710" size="1180,1" />
				<widget font="Regular;32" halign="center" name="status" position="13,717" size="1175,47" valign="center" />
				<widget font="Regular;32" halign="center" name="statusbar" position="101,770" size="986,44" valign="center" />
				<widget font="Regular;32" halign="center" name="description" position="13,653" size="1175,51" valign="center" />
				<ePixmap pixmap="skin_default/icons/info.png" position="10,770" size="80,40" />
				<ePixmap pixmap="skin_default/icons/menu.png" position="1110,770" size="80,40" />
			</screen>"""
	else:
		skin = """
			<screen position="center,center" size="820,520" title="EPG Import Configuration">
				<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/green.png" position="210,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/yellow.png" position="410,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/blue.png" position="610,5" size="200,40" />
				<widget name="key_red" position="10,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#9f1313" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_green" position="210,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#1f771f" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_yellow" position="410,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#a08500" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_blue" position="610,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#18188b" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<eLabel position="10,50" size="800,1" backgroundColor="grey" />
				<widget name="config" position="10,60" size="800,360" enableWrapAround="1" scrollbarMode="showOnDemand" />
				<eLabel position="10,425" size="800,1" backgroundColor="grey" />
				<widget name="status" position="87,486" size="660,32" font="Regular;22" halign="center" valign="center" />
				<widget name="statusbar" position="13,452" size="798,33" font="Regular;22" halign="center" valign="center" />
				<widget name="description" position="12,425" size="795,30" font="Regular;22" halign="center" valign="center" />
				<ePixmap pixmap="skin_default/buttons/key_info.png" position="10,488" size="50,25" />
				<ePixmap pixmap="skin_default/buttons/key_menu.png" position="760,488" size="50,25" />
			</screen>"""

	def __init__(self, session, args=0):
		self.session = session
		self.skin = EPGImportConfig.skin
		Screen.__init__(self, session)
		# self.setup_title = _("EPG Import Configuration")
		self["status"] = Label()
		self["statusbar"] = Label()
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["key_yellow"] = Button(_("Manual"))
		self["key_blue"] = Button(_("Sources"))
		self["description"] = Label("")
		self["setupActions"] = ActionMap(
			["SetupActions", "ColorActions", "TimerEditActions", "MovieSelectionActions"],
			{
				"red": self.keyRed,
				"green": self.keyGreen,
				"yellow": self.doimport,           # Tasto giallo - Importazione
				"blue": self.dosources,            # Tasto blu - Fonti
				"cancel": self.extnok,
				"ok": self.keyOk,
				"log": self.keyInfo,               # Tasto log - Info aggiuntive
				"contextMenu": self.openMenu
			},
			-1
		)
		# ConfigListScreen.__init__(self, [], session=self.session)
		self.lastImportResult = None
		self.list = []
		self.onChangedEntry = []
		ConfigListScreen.__init__(self, self.list, session=self.session, on_change=self.changedEntry)
		self.prev_onlybouquet = config.plugins.epgimport.import_onlybouquet.value
		self.initConfig()
		self.createSetup()
		self.filterStatusTemplate = _("Filtering: %s\nPlease wait!")
		self.importStatusTemplate = _("Importing: %s\n%s events")
		self.updateTimer = eTimer()
		if isDreambox:
			self.updateTimer_conn = self.updateTimer.timeout.connect(self.updateStatus)
		else:
			self.updateTimer.callback.append(self.updateStatus)
		self.updateTimer.start(2000)
		self.updateStatus()
		self.onLayoutFinish.append(self.__layoutFinished)

	def changedEntry(self):
		for x in self.onChangedEntry:
			x()

	def getCurrentEntry(self):
		return self["config"].getCurrent()[0]

	def getCurrentValue(self):
		return str(self["config"].getCurrent()[1].getText())

	def createSummary(self):
		from Screens.Setup import SetupSummary
		return SetupSummary

	def __layoutFinished(self):
		pass

	def initConfig(self):
		def getPrevValues(section):
			res = {}
			for (key, val) in section.content.items.items():
				if isinstance(val, ConfigSubsection):
					res[key] = getPrevValues(val)
				else:
					res[key] = val.value
			return res
		self.EPG = config.plugins.epgimport
		self.prev_values = getPrevValues(self.EPG)
		self.cfg_enabled = getConfigListEntry(_("Automatic import EPG"), self.EPG.enabled)
		self.cfg_pathdb = getConfigListEntry(_("Path DB EPG"), self.EPG.pathdb)
		self.cfg_wakeup = getConfigListEntry(_("Automatic start time"), self.EPG.wakeup)
		self.cfg_deepstandby = getConfigListEntry(_("When in deep standby"), self.EPG.deepstandby)
		self.cfg_shutdown = getConfigListEntry(_("Return to deep standby after import"), self.EPG.shutdown)
		self.cfg_standby_afterwakeup = getConfigListEntry(_("Standby at startup"), self.EPG.standby_afterwakeup)
		self.cfg_day_profile = getConfigListEntry(_("Choice days for start import"), self.EPG.day_profile)
		self.cfg_runboot = getConfigListEntry(_("Start import after booting up"), self.EPG.runboot)
		self.cfg_import_onlybouquet = getConfigListEntry(_("Load EPG only services in bouquets"), self.EPG.import_onlybouquet)
		self.cfg_import_onlyiptv = getConfigListEntry(_("Load EPG only for IPTV channels"), self.EPG.import_onlyiptv)
		self.cfg_runboot_day = getConfigListEntry(_("Consider setting \"Days Profile\""), self.EPG.runboot_day)
		self.cfg_runboot_restart = getConfigListEntry(_("Skip import on restart GUI"), self.EPG.runboot_restart)
		self.cfg_showinextensions = getConfigListEntry(_("Show \"EPGImport\" in extensions"), self.EPG.showinextensions)
		self.cfg_showinplugins = getConfigListEntry(_("Show \"EPGImport\" in plugins"), self.EPG.showinplugins)
		self.cfg_showinmainmenu = getConfigListEntry(_("Show \"EPG Importer\" in main menu"), self.EPG.showinmainmenu)
		self.cfg_longDescDays = getConfigListEntry(_("Load long descriptions up to X days"), self.EPG.longDescDays)
		self.cfg_parse_autotimer = getConfigListEntry(_("Run AutoTimer after import"), self.EPG.parse_autotimer)
		self.cfg_clear_oldepg = getConfigListEntry(_("Clearing current EPG before import"), config.plugins.epgimport.clear_oldepg)

	def createSetup(self):
		list = [self.cfg_enabled]
		if self.EPG.enabled.value:
			list.append(self.cfg_wakeup)
			list.append(self.cfg_deepstandby)
			if self.EPG.deepstandby.value == "wakeup":
				list.append(self.cfg_shutdown)
				if not self.EPG.shutdown.value:
					list.append(self.cfg_standby_afterwakeup)
		list.append(self.cfg_day_profile)
		list.append(self.cfg_runboot)
		if self.EPG.runboot.value != "4":
			list.append(self.cfg_runboot_day)
			if self.EPG.runboot.value == "1" or self.EPG.runboot.value == "2":
				list.append(self.cfg_runboot_restart)
		list.append(self.cfg_pathdb)
		list.append(self.cfg_showinextensions)
		list.append(self.cfg_showinplugins)
		list.append(self.cfg_showinmainmenu)
		list.append(self.cfg_import_onlybouquet)
		list.append(self.cfg_import_onlyiptv)
		if hasattr(eEPGCache, 'flushEPG'):
			list.append(self.cfg_clear_oldepg)
		list.append(self.cfg_longDescDays)
		if fileExists("/usr/lib/enigma2/python/Plugins/Extensions/AutoTimer/plugin.py"):
			try:
				from Plugins.Extensions.AutoTimer.AutoTimer import AutoTimer
				list.append(self.cfg_parse_autotimer)
			except:
				log.write("[EPGImport] AutoTimer Plugin not installed")
		self["config"].list = list
		self["config"].l.setList(list)

	def newConfig(self):
		cur = self["config"].getCurrent()
		if cur in (self.cfg_enabled, self.cfg_shutdown, self.cfg_deepstandby, self.cfg_runboot):
			self.createSetup()

	def keyRed(self):
		def setPrevValues(section, values):
			for (key, val) in section.content.items.items():
				value = values.get(key, None)
				if value is not None:
					if isinstance(val, ConfigSubsection):
						setPrevValues(val, value)
					else:
						val.value = value
		setPrevValues(self.EPG, self.prev_values)
		self.keyGreen()

	def extnok(self, answer=None):
		if self["config"].isChanged():
			if answer is None:
				self.session.openWithCallback(self.extnok, MessageBox, _("Really close without saving settings?"))
			elif answer:
				for x in self["config"].list:
					x[1].cancel()
		self.close(True, self.session)

	def keyGreen(self):
		self.updateTimer.stop()
		if not fileExists("/usr/lib/enigma2/python/Plugins/Extensions/AutoTimer/plugin.py") and self.EPG.parse_autotimer.value:
			self.EPG.parse_autotimer.value = False
		if self.EPG.shutdown.value:
			self.EPG.standby_afterwakeup.value = False
		# self.EPG.save()
		if self.prev_onlybouquet != config.plugins.epgimport.import_onlybouquet.value or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			EPGConfig.channelCache = {}
		self.save()

	def save(self):
		if self["config"].isChanged():
			for x in self["config"].list:
				x[1].save()
			configfile.save()
			self.EPG.save()
			self.session.open(MessageBox, _("Settings saved successfully !"), MessageBox.TYPE_INFO, timeout=5)
		self.close(True, self.session)

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.newConfig()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.newConfig()

	def keyOk(self):
		ConfigListScreen.keyOK(self)
		sel = self["config"].getCurrent()[1]
		if sel and sel == self.EPG.day_profile:
			self.session.open(EPGImportProfile)
		elif sel == self.EPG.pathdb:
			self.setting = "pathdb"
			if hasattr(config.misc.epgcache_filename, 'value'):
				self.openDirectoryBrowser(self.EPG.pathdb.value, self.setting)
				print('new value=', self.EPG.pathdb.getValue())
			else:
				print("[EPGImport] Invalid configuration for epgcache_filename")
		else:
			return

	def openDirectoryBrowser(self, path, itemcfg):
		try:
			callback_map = {
				"pathdb": self.openDirectoryBrowserCB(config.misc.epgcache_filename),
			}
			if itemcfg in callback_map:
				self.session.openWithCallback(
					callback_map[itemcfg],
					LocationBox,
					windowTitle=_("Choose Directory:"),
					text=_("Choose directory"),
					currDir=str(path),
					bookmarks=config.movielist.videodirs,
					autoAdd=True,
					editDir=True,
					inhibitDirs=["/bin", "/boot", "/dev", "/home", "/lib", "/proc", "/run", "/sbin", "/sys", "/usr", "/var"]
				)
		except Exception as e:
			print("[EPGImport] Error opening directory browser:", e)

	def openDirectoryBrowserCB(self, config_entry):
		def callback(path):
			if path is not None:
				pathz = os.path.join(path, 'epg.dat')
				print("epg path=:", pathz)
				self.EPG.pathdb.setValue(pathz)
		return callback

	def updateStatus(self):
		text = ""
		global isFilterRunning, filterCounter
		if isFilterRunning == 1:
			text = self.filterStatusTemplate % (str(filterCounter))
		elif epgimport.isImportRunning():
			src = epgimport.source
			text = self.importStatusTemplate % (src.description, epgimport.eventCount)

		self["status"].setText(text)
		if lastImportResult and (lastImportResult != self.lastImportResult):
			start, count = lastImportResult
			try:
				if isinstance(start, str):
					start = time.mktime(time.strptime(start, "%Y-%m-%d %H:%M:%S"))
				elif not isinstance(start, (int, float)):
					raise ValueError("Start value is not a valid timestamp or string")

				# Chiama FuzzyTime con il timestamp corretto
				d, t = FuzzyTime(int(start), inPast=True)
			except Exception as e:
				print("[EPGImport] Errore con FuzzyTime:", e)
				try:
					d, t = FuzzyTime(int(start))
					print("[EPGImport] Metodo FuzzyTime(int(start)")
				except Exception as e:
					print("[EPGImport] Fallito anche il fallback con FuzzyTime:", e)
					d, t = _("unknown"), _("unknown")
			self["statusbar"].setText(_("Last: %s %s, %d events") % (d, t, count))
			self.lastImportResult = lastImportResult

	def keyInfo(self):
		last_import = config.plugins.extra_epgimport.last_import.value
		self.session.open(MessageBox, _("Last import: %s events") % (last_import), type=MessageBox.TYPE_INFO)

	def doimport(self, one_source=None):
		if epgimport.isImportRunning():
			log.write("[EPGImport] Already running, won't start again")
			self.session.open(MessageBox, _("EPGImport\nImport of epg data is still in progress. Please wait."), MessageBox.TYPE_ERROR, timeout=10, close_on_any_key=True)
			return
		if self.prev_onlybouquet != config.plugins.epgimport.import_onlybouquet.value or (autoStartTimer is not None and autoStartTimer.prev_multibouquet != config.usage.multibouquet.value):
			EPGConfig.channelCache = {}
		if one_source is None:
			cfg = EPGConfig.loadUserSettings()
		else:
			cfg = one_source
		sources = [s for s in EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"])]
		EPGImport.ServerStatusList = {}
		if not sources:
			self.session.open(MessageBox, _("No active EPG sources found, nothing to do"), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			return
		# make it a stack, first on top.
		sources.reverse()
		epgimport.sources = sources
		self.session.openWithCallback(self.do_import_callback, MessageBox, _("EPGImport\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?"), MessageBox.TYPE_YESNO, timeout=15, default=True)

	def do_import_callback(self, confirmed):
		if not confirmed:
			return
		try:
			startImport()
		except Exception as e:
			# log.write
			self.session.open(MessageBox, _("EPGImport Plugin\nFailed to start:\n") + str(e), MessageBox.TYPE_ERROR, timeout=15, close_on_any_key=True)
		self.updateStatus()

	def dosources(self):
		self.session.openWithCallback(self.sourcesDone, EPGImportSources)

	def sourcesDone(self, confirmed, sources, cfg):
		# Called with True and list of config items on Okay.
		# log.write("sourcesDone(): ", confirmed, sources)
		if cfg is not None:
			self.doimport(one_source=cfg)

	def openMenu(self):
		menu = [(_("Show log"), self.showLog), (_("Ignore services list"), self.openIgnoreList)]
		text = _("Select action")

		def setAction(choice):
			if choice:
				choice[1]()
		self.session.openWithCallback(setAction, ChoiceBox, title=text, list=menu)

	def openIgnoreList(self):
		self.session.open(filtersServices.filtersServicesSetup)

	def showLog(self):
		self.session.open(EPGImportLogx)


class EPGImportSources(Screen):
	"Pick sources from config"
	if sz_w >= 1920:
		skin = """
			<screen position="center,center" size="1200,820" title="EPG Import Sources" >
				<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/green.png" position="305,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/yellow.png" position="600,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/blue.png" position="895,5" size="295,70" />
				<widget backgroundColor="#9f1313" font="Regular;30" halign="center" name="key_red" position="10,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#1f771f" font="Regular;30" halign="center" name="key_green" position="305,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#a08500" font="Regular;30" halign="center" name="key_yellow" position="600,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#18188b" font="Regular;30" halign="center" name="key_blue" position="895,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<eLabel backgroundColor="grey" position="10,80" size="1180,1" />
				<widget enableWrapAround="1" name="list" position="10,90" size="1180,700" scrollbarMode="showOnDemand" />
			</screen>"""
	else:
		skin = """
			<screen position="center,center" size="820,520" title="EPG Import Sources" >
				<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/green.png" position="210,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/yellow.png" position="410,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/blue.png" position="610,5" size="200,40" />
				<widget name="key_red" position="10,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#9f1313" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_green" position="210,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#1f771f" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_yellow" position="410,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#a08500" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_blue" position="610,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#18188b" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<eLabel position="10,50" size="800,1" backgroundColor="grey" />
				<widget name="list" position="10,60" size="800,450" enableWrapAround="1" scrollbarMode="showOnDemand" />
			</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["key_yellow"] = Button(_('Import'))
		self["key_blue"] = Button(_('Import from Git'))
		cfg = EPGConfig.loadUserSettings()
		self.container = None
		filter = cfg["sources"]
		tree = []
		cat = None
		for x in EPGConfig.enumSources(CONFIG_PATH, filter=None, categories=True):
			if hasattr(x, 'description'):
				sel = (filter is None) or (x.description in filter)
				entry = (x.description, x.description, sel)
				if cat is None:
					# If no category defined, use a default one.
					cat = ExpandableSelectionList.category("[.]")
					tree.append(cat)
				cat[0][2].append(entry)
				if sel:
					ExpandableSelectionList.expand(cat, True)
			else:
				cat = ExpandableSelectionList.category(x)
				tree.append(cat)
		self["list"] = ExpandableSelectionList.ExpandableSelectionList(tree, enableWrapAround=True)
		if tree:
			self["key_yellow"].show()
			self['key_blue'].hide()
		else:
			self["key_yellow"].hide()
			self["key_blue"].show()
		self["setupActions"] = ActionMap(
			["SetupActions", "ColorActions", "MenuActions"],
			{
				"red": self.cancel,
				"green": self.save,
				"yellow": self.do_import,        # Tasto giallo - Importazione
				"blue": self.git_import,         # Tasto blu - Importazione tramite Git
				"save": self.save,
				"cancel": self.cancel,
				"menu": self.do_reset,
				"ok": self["list"].toggleSelection  # Tasto OK - Toggle selezione nella lista
			},
			-2
		)
		# self.setTitle(_("EPG Import Sources"))

	def git_import(self):
		self.session.openWithCallback(
			self.install_update,
			MessageBox,
			_("Do you want to update Source now?"),
			MessageBox.TYPE_YESNO
		)

	def install_update(self, answer=False):
		if answer:
			# title = (_("Executing... \nPlease Wait..."))
			installer_url = "https://raw.githubusercontent.com/Belfagor2005/EPGImport-99/main/installer_source.sh"
			cmd = "wget -q --no-check-certificate " + installer_url + " -O - | /bin/bash"
			if self.container:
				del self.container
			self.container = eConsoleAppContainer()
			self.run = 0
			self.finished = False
			try:  # DreamOS
				self.container.appClosed.append(self.after_update)
				# self.container.dataAvail.append(self.dataAvail)
			except:
				self.container.appClosed_conn = self.container.appClosed.connect(self.after_update)
				# self.container.dataAvail_conn = self.container.dataAvail.connect(self.dataAvail)

			# self.container.appClosed.append(self.after_update)
			if self.container.execute(cmd):
				self.after_update(-1)

			print("Update completed")
			self.session.open(
				MessageBox,
				_("Source files Imported!"),
				MessageBox.TYPE_INFO,
				timeout=5
			)

		else:
			self.session.open(
				MessageBox,
				_("Update Aborted!"),
				MessageBox.TYPE_INFO,
				timeout=3
			)

	def after_update(self, retval):
		if retval:
			if self.container:
				try:  # DreamOS
					self.container.appClosed.remove(self.after_update)
					# self.container.dataAvail.remove(self.dataAvail)
				except:
					self.container.appClosed_conn = None
					# self.container.dataAvail_conn = None
				self.container.kill()
		# if self.container:
			# self.container.appClosed.remove(self.after_update)
			# self.container = None
		self.cfg_imp()
		self.save()

	def cfg_imp(self):
		import shutil
		self.source_cfg = resolveFilename(SCOPE_PLUGINS, "Extensions/EPGImport/epgimport.conf")
		dest_cfg = '/etc/enigma2'  # Configurazione destinazione
		if not os.path.exists(CONFIG_PATH):
			try:
				os.makedirs(CONFIG_PATH)
			except Exception as e:
				print("Error creating directory:", CONFIG_PATH, ":", str(e))
				return
		if not os.path.exists(os.path.join(dest_cfg, 'epgimport.conf')):
			try:
				shutil.copy(self.source_cfg, dest_cfg)
				print("File copied:", self.source_cfg, "->", dest_cfg)
			except Exception as e:
				print("Error while copying configuration file:", self.source_cfg, ":", str(e))
		return

	"""
	def git_import(self):
		self.source_path = resolveFilename(SCOPE_PLUGINS, "Extensions/EPGImport/source")
		self.source_cfg = resolveFilename(SCOPE_PLUGINS, "Extensions/EPGImport/epgimport.conf")
		dest_cfg = '/etc/enigma2'  # Configurazione destinazione
		if not os.path.exists(self.source_path):
			print("Folder not exist:", self.source_path)
			return
		if not os.path.exists(CONFIG_PATH):
			try:
				os.makedirs(CONFIG_PATH)
			except Exception as e:
				print("Error creating directory:", CONFIG_PATH, ":", str(e))
				return
		if not os.path.exists(os.path.join(dest_cfg, 'epgimport.conf')):
			try:
				shutil.copy(self.source_cfg, dest_cfg)
				print("File copied:", self.source_cfg, "->", dest_cfg)
			except Exception as e:
				print("Error while copying configuration file:", self.source_cfg, ":", str(e))
				return
		for filename in os.listdir(self.source_path):
			source_file = os.path.join(self.source_path, filename)
			dest_file = os.path.join(CONFIG_PATH, filename)
			if os.path.isfile(source_file):
				try:
					shutil.copy(source_file, dest_file)
					print("File copied:", source_file, "->", dest_file)
				except Exception as e:
					print("Error while copying file:", source_file, ":", str(e))
		self.session.open(MessageBox, _("Source files Imported!"), MessageBox.TYPE_INFO, timeout=5)
		self.save()
	"""

	def save(self):
		# Make the entries unique through a set
		sources = list(set([item[1] for item in self["list"].enumSelected()]))
		# log.write("[EPGImport] Selected sources:", sources)
		EPGConfig.storeUserSettings(sources=sources)
		self.close(True, sources, None)

	def cancel(self):
		self.close(False, None, None)

	def do_import(self):
		list = self["list"].list
		if list and len(list) > 0:
			try:
				idx = self["list"].getSelectedIndex()
				item = self["list"].list[idx][0]
				source = [item[1] or ""]
				cfg = {"sources": source}
				# log.write("[EPGImport] Selected source: ", source)
			except Exception as e:
				log.write("[EPGImport] Error at selected source: %s", e)
			else:
				if cfg["sources"] != "":
					self.close(False, None, cfg)

	def do_reset(self):
		log.write("[EPGImport] create empty epg.db")
		self.epginstance = eEPGCache.getInstance()
		if os.path.exists(config.misc.epgcache_filename.value):
			os.remove(config.misc.epgcache_filename.value)
		connection = sqlite.connect(config.misc.epgcache_filename.value, timeout=10)
		connection.text_factory = str
		cursor = connection.cursor()
		cursor.execute("CREATE TABLE T_Service (id INTEGER PRIMARY KEY, sid INTEGER NOT NULL, tsid INTEGER, onid INTEGER, dvbnamespace INTEGER, changed DATETIME NOT NULL DEFAULT current_timestamp)")
		cursor.execute("CREATE TABLE T_Source (id INTEGER PRIMARY KEY, source_name TEXT NOT NULL, priority INTEGER NOT NULL, changed DATETIME NOT NULL DEFAULT current_timestamp)")
		cursor.execute("CREATE TABLE T_Title (id INTEGER PRIMARY KEY, hash INTEGER NOT NULL UNIQUE, title TEXT NOT NULL, changed DATETIME NOT NULL DEFAULT current_timestamp)")
		cursor.execute("CREATE TABLE T_Short_Description (id INTEGER PRIMARY KEY, hash INTEGER NOT NULL UNIQUE, short_description TEXT NOT NULL, changed DATETIME NOT NULL DEFAULT current_timestamp)")
		cursor.execute("CREATE TABLE T_Extended_Description (id INTEGER PRIMARY KEY, hash INTEGER NOT NULL UNIQUE, extended_description TEXT NOT NULL, changed DATETIME NOT NULL DEFAULT current_timestamp)")
		cursor.execute("CREATE TABLE T_Event (id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL, begin_time INTEGER NOT NULL, duration INTEGER NOT NULL, source_id INTEGER NOT NULL, dvb_event_id INTEGER, changed DATETIME NOT NULL DEFAULT current_timestamp)")
		cursor.execute("CREATE TABLE T_Data (event_id INTEGER NOT NULL, title_id INTEGER, short_description_id INTEGER, extended_description_id INTEGER, iso_639_language_code TEXT NOT NULL, changed DATETIME NOT NULL DEFAULT current_timestamp)")
		cursor.execute("CREATE INDEX data_title ON T_Data (title_id)")
		cursor.execute("CREATE INDEX data_shortdescr ON T_Data (short_description_id)")
		cursor.execute("CREATE INDEX data_extdescr ON T_Data (extended_description_id)")
		cursor.execute("CREATE INDEX service_sid ON T_Service (sid)")
		cursor.execute("CREATE INDEX event_service_id_begin_time ON T_Event (service_id, begin_time)")
		cursor.execute("CREATE INDEX event_dvb_id ON T_Event (dvb_event_id)")
		cursor.execute("CREATE INDEX data_event_id ON T_Data (event_id)")
		cursor.execute("CREATE TRIGGER tr_on_delete_cascade_t_event AFTER DELETE ON T_Event FOR EACH ROW BEGIN DELETE FROM T_Data WHERE event_id = OLD.id; END")
		cursor.execute("CREATE TRIGGER tr_on_delete_cascade_t_service_t_event AFTER DELETE ON T_Service FOR EACH ROW BEGIN DELETE FROM T_Event WHERE service_id = OLD.id; END")
		cursor.execute("CREATE TRIGGER tr_on_delete_cascade_t_data_t_title AFTER DELETE ON T_Data FOR EACH ROW WHEN ((SELECT event_id FROM T_Data WHERE title_id = OLD.title_id LIMIT 1) ISNULL) BEGIN DELETE FROM T_Title WHERE id = OLD.title_id; END")
		cursor.execute("CREATE TRIGGER tr_on_delete_cascade_t_data_t_short_description AFTER DELETE ON T_Data FOR EACH ROW WHEN ((SELECT event_id FROM T_Data WHERE short_description_id = OLD.short_description_id LIMIT 1) ISNULL) BEGIN DELETE FROM T_Short_Description WHERE id = OLD.short_description_id; END")
		cursor.execute("CREATE TRIGGER tr_on_delete_cascade_t_data_t_extended_description AFTER DELETE ON T_Data FOR EACH ROW WHEN ((SELECT event_id FROM T_Data WHERE extended_description_id = OLD.extended_description_id LIMIT 1) ISNULL) BEGIN DELETE FROM T_Extended_Description WHERE id = OLD.extended_description_id; END")
		cursor.execute("CREATE TRIGGER tr_on_update_cascade_t_data AFTER UPDATE ON T_Data FOR EACH ROW WHEN (OLD.title_id <> NEW.title_id AND ((SELECT event_id FROM T_Data WHERE title_id = OLD.title_id LIMIT 1) ISNULL)) BEGIN DELETE FROM T_Title WHERE id = OLD.title_id; END")
		cursor.execute("INSERT INTO T_Source (id,source_name,priority) VALUES('0','Sky Private EPG','0')")
		cursor.execute("INSERT INTO T_Source (id,source_name,priority) VALUES('1','DVB Now/Next Table','0')")
		cursor.execute("INSERT INTO T_Source (id,source_name,priority) VALUES('2','DVB Schedule (same Transponder)','0')")
		cursor.execute("INSERT INTO T_Source (id,source_name,priority) VALUES('3','DVB Schedule Other (other Transponder)','0')")
		cursor.execute("INSERT INTO T_Source (id,source_name,priority) VALUES('4','Viasat','0')")
		connection.commit()
		cursor.close()
		connection.close()
		log.write("[EPGImport] loading empty epg.db")
		eEPGCache.load(self.epginstance)
		self.session.open(MessageBox, _("EPG database was emptied"),  MessageBox.TYPE_INFO)


class EPGImportProfile(ConfigListScreen, Screen):
	if sz_w >= 1920:
		skin = """
		<screen position="center,center" size="1200,820" title="EPGImportProfile" >
			<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="300,70" />
			<ePixmap pixmap="skin_default/buttons/green.png" position="310,5" size="300,70" />
			<widget backgroundColor="#9f1313" font="Regular;30" halign="center" name="key_red" position="10,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="300,70" transparent="1" valign="center" zPosition="1" />
			<widget backgroundColor="#1f771f" font="Regular;30" halign="center" name="key_green" position="310,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="300,70" transparent="1" valign="center" zPosition="1" />
			<widget font="Regular;34" halign="right" position="1050,25" render="Label" size="120,40" source="global.CurrentTime">
				<convert type="ClockToText">Default</convert>
			</widget>
			<widget font="Regular;34" halign="right" position="800,25" render="Label" size="240,40" source="global.CurrentTime">
				<convert type="ClockToText">Date</convert>
			</widget>
			<eLabel backgroundColor="grey" position="10,80" size="1180,1" />
			<widget enableWrapAround="1" name="config" position="10,90" scrollbarMode="showOnDemand" size="1180,720" />
		</screen>"""
	else:
		skin = """
		<screen position="center,center" size="820,520" title="EPGImportProfile" >
			<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="200,40"/>
			<ePixmap pixmap="skin_default/buttons/green.png" position="210,5" size="200,40"/>
			<widget name="key_red" position="10,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
			<widget name="key_green" position="210,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
			<eLabel position="10,50" size="800,1" backgroundColor="grey"/>
			<widget name="config" position="10,55" size="800,450" enableWrapAround="1" scrollbarMode="showOnDemand"/>
		</screen>"""

	def __init__(self, session, args=0):
		self.session = session
		Screen.__init__(self, session)
		# self.setTitle(_("Days Profile"))
		self.list = []
		for i in range(7):
			self.list.append(getConfigListEntry(weekdays[i], config.plugins.extra_epgimport.day_import[i]))
		ConfigListScreen.__init__(self, self.list)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))
		self["setupActions"] = ActionMap(
			["SetupActions", "ColorActions"],
			{
				"red": self.cancel,
				"green": self.save,
				"save": self.save,
				"cancel": self.cancel,
				"ok": self.save
			},
			-2
		)
		self.onLayoutFinish.append(self.setCustomTitle)

	def setCustomTitle(self):
		# self.setTitle(_("Days Profile"))
		pass

	def save(self):
		if not config.plugins.extra_epgimport.day_import[0].value:
			if not config.plugins.extra_epgimport.day_import[1].value:
				if not config.plugins.extra_epgimport.day_import[2].value:
					if not config.plugins.extra_epgimport.day_import[3].value:
						if not config.plugins.extra_epgimport.day_import[4].value:
							if not config.plugins.extra_epgimport.day_import[5].value:
								if not config.plugins.extra_epgimport.day_import[6].value:
									self.session.open(MessageBox, _("You may not use this settings!\nAt least one day a week should be included!"), MessageBox.TYPE_INFO, timeout=6)
									return
		for x in self["config"].list:
			x[1].save()
		self.close()

	def cancel(self):
		for x in self["config"].list:
			x[1].cancel()
		self.close()


class EPGImportLogx(Screen):
	if sz_w >= 1920:
		skin = """
			<screen position="center,center" size="1200,820" title="EPG Import Log"  >
				<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/green.png" position="305,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/yellow.png" position="600,5" size="295,70" />
				<ePixmap pixmap="skin_default/buttons/blue.png" position="895,5" size="295,70" />
				<widget backgroundColor="#9f1313" font="Regular;30" halign="center" name="key_red" position="10,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#1f771f" font="Regular;30" halign="center" name="key_green" position="305,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#a08500" font="Regular;30" halign="center" name="key_yellow" position="600,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<widget backgroundColor="#18188b" font="Regular;30" halign="center" name="key_blue" position="895,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" transparent="1" valign="center" zPosition="1" />
				<eLabel backgroundColor="grey" position="10,80" size="1180,1" />
				<!--  <widget name="list" position="10,90" size="1180,720" /> -->
				<widget font="Regular;34" name="list" position="10,90" size="1180,720" halign="left" valign="top" />
			</screen>"""
	else:
		skin = """
			<screen position="center,center" size="820,520" title="EPG Import Log" >
				<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/green.png" position="210,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/yellow.png" position="410,5" size="200,40" />
				<ePixmap pixmap="skin_default/buttons/blue.png" position="610,5" size="200,40" />
				<widget name="key_red" position="10,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#9f1313" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_green" position="210,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#1f771f" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_yellow" position="410,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#a08500" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<widget name="key_blue" position="610,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" foregroundColor="white" backgroundColor="#18188b" transparent="1" shadowColor="black" shadowOffset="-2,-2" />
				<eLabel position="10,50" size="800,1" backgroundColor="grey" />
				<widget name="list" position="10,60" size="800,450" font="Regular;22"/>
			</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self.log = log
		self["key_red"] = Button(_("Clear"))
		self["key_green"] = Button()
		self["key_yellow"] = Button()
		self["key_blue"] = Button(_("Save"))
		# # crash on scrolllabel
		# self["list"] = ScrollLabel("")
		# self["list"].setText(self.log.getvalue())
		self.text_lines = self.log.getvalue().splitlines()
		self.current_line = 0
		self.visible_lines_count = 20
		self["list"] = Label("")
		self.updateText()
		self["actions"] = ActionMap(["DirectionActions", "OkCancelActions", "ColorActions", "MenuActions"], {
			"red": self.clear,
			"green": self.cancel,
			"yellow": self.cancel,
			"save": self.save,
			"blue": self.save,
			"cancel": self.cancel,
			"ok": self.cancel,
			"left": self.scrollUp,
			"right": self.scrollDown,
			"up": self.scrollUp,
			"down": self.scrollDown,
			"pageUp": self.scrollUp,
			"pageDown": self.scrollDown,
			"menu": self.cancel}, -2)
		self.onLayoutFinish.append(self.setCustomTitle)

	def setCustomTitle(self):
		# self.setTitle(_("EPG Import Log"))
		pass

	def updateText(self):
		"""Aggiorna il testo mostrato nel `Label` in base alla riga corrente."""
		visible_lines = self.text_lines[self.current_line:self.current_line + self.visible_lines_count]
		self["list"].setText("\n".join(visible_lines))

	def scrollUp(self):
		"""Scorri il testo verso l'alto di 20 righe."""
		if self.current_line > 0:
			self.current_line = max(0, self.current_line - self.visible_lines_count)  # Non andare sotto la riga 0
			self.updateText()

	def scrollDown(self):
		"""Scorri il testo verso il basso di 20 righe."""
		if self.current_line + self.visible_lines_count < len(self.text_lines):
			self.current_line = min(len(self.text_lines) - self.visible_lines_count, self.current_line + self.visible_lines_count)
			self.updateText()

	def save(self):
		try:
			with open('/tmp/epgimport.log', 'w') as f:
				f.write(self.log.getvalue())(MessageBox, _("Write to /tmp/epgimport.log"), MessageBox.TYPE_INFO, timeout=5, close_on_any_key=True)
		except Exception as e:
			self["list"].setText("Failed to write /tmp/epgimport.log:str" + str(e))
		self.close(True)

	def cancel(self):
		self.close(False)

	def clear(self):
		self.log.logfile.write("")
		self.log.logfile.truncate()
		self.close(False)


class EPGImportDownloader(MessageBox):
	def __init__(self, session):
		MessageBox.__init__(self, session, _("Last import: ") + config.plugins.extra_epgimport.last_import.value + _(" events\n") + _("\nImport of epg data will start.\nThis may take a few minutes.\nIs this ok?"), MessageBox.TYPE_YESNO)
		self.skinName = "MessageBox"


def msgClosed(ret):
	global autoStartTimer
	if ret:
		if autoStartTimer is not None and not epgimport.isImportRunning():
			log.write("[EPGImport] Run manual starting import")
			autoStartTimer.runImport()


def start_import(session, **kwargs):
	session.openWithCallback(msgClosed, EPGImportDownloader)


def main(session, **kwargs):
	session.openWithCallback(doneConfiguring, EPGImportConfig)


def main_menu(menuid, **kwargs):
	if menuid == "mainmenu" and config.plugins.epgimport.showinmainmenu.getValue():
		return [(_("EPG Importer"), start_import, "epgimporter", 45)]
	else:
		return []


def doneConfiguring(session, retval):
	'''user has closed configuration, check new values....'''
	if retval is True:
		if autoStartTimer is not None:
			autoStartTimer.update()


def doneImport(reboot=False, epgfile=None):
	global _session, lastImportResult, BouquetChannelListList, serviceIgnoreList
	BouquetChannelListList = None
	serviceIgnoreList = None
	#
	timestamp = time.time()
	formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
	lastImportResult = (formatted_time, epgimport.eventCount)
	# lastImportResult = (time.time(), epgimport.eventCount)
	try:
		start, count = lastImportResult
		localtime = time.asctime(time.localtime(time.time()))
		lastimport = "%s, %d" % (localtime, count)
		config.plugins.extra_epgimport.last_import.value = lastimport
		config.plugins.extra_epgimport.last_import.save()
		log.write("[EPGImport] Save last import date and count event")
	except:
		log.write("[EPGImport] Error to save last import date and count event")
	if reboot:
		if Screens.Standby.inStandby:
			log.write("[EPGImport] Restart enigma2")
			restartEnigma(True)
		else:
			msg = _("EPG Import finished, %d events") % epgimport.eventCount + "\n" + _("You must restart Enigma2 to load the EPG data,\nis this OK?")
			_session.openWithCallback(restartEnigma, MessageBox, msg, MessageBox.TYPE_YESNO, timeout=15, default=True)
			log.write("[EPGImport] Need restart enigma2")
	else:
		if config.plugins.epgimport.parse_autotimer.value and fileExists("/usr/lib/enigma2/python/Plugins/Extensions/AutoTimer/plugin.py"):
			try:
				from Plugins.Extensions.AutoTimer.plugin import autotimer
				if autotimer is None:
					from Plugins.Extensions.AutoTimer.AutoTimer import AutoTimer
					autotimer = AutoTimer()
				autotimer.readXml()
				checkDeepstandby(_session, parse=True)
				autotimer.parseEPGAsync(simulateOnly=False)
				log.write("[EPGImport] Run start parse autotimers")
			except:
				log.write("[EPGImport] Could not start autotimers")
				checkDeepstandby(_session, parse=False)
		else:
			checkDeepstandby(_session, parse=False)


class checkDeepstandby:
	def __init__(self, session, parse=False):
		self.session = session
		if config.plugins.epgimport.enabled.value:
			if parse:
				self.FirstwaitCheck = eTimer()
				if isDreambox:
					self.FirstwaitCheck_conn = self.FirstwaitCheck.timeout.connect(self.runCheckDeepstandby)
				else:
					self.FirstwaitCheck.callback.append(self.runCheckDeepstandby)
				self.FirstwaitCheck.startLongTimer(600)
				log.write("[EPGImport] Wait for parse autotimers 30 sec.")
			else:
				self.runCheckDeepstandby()

	def runCheckDeepstandby(self):
		log.write("[EPGImport] Run check deep standby after import")
		if config.plugins.epgimport.shutdown.value and config.plugins.epgimport.deepstandby.value == 'wakeup':
			if config.plugins.epgimport.deepstandby_afterimport.value and getFPWasTimerWakeup():
				config.plugins.epgimport.deepstandby_afterimport.value = False
				if Screens.Standby.inStandby and not self.session.nav.getRecordings() and not Screens.Standby.inTryQuitMainloop:
					log.write("[EPGImport] Returning to deep standby after wake up for import")
					self.session.open(Screens.Standby.TryQuitMainloop, 1)
				else:
					log.write("[EPGImport] No return to deep standby, not standby or running recording")


def restartEnigma(confirmed):
	if not confirmed:
		return
		# save state of enigma, so we can return to previeus state
	if Screens.Standby.inStandby:
		try:
			open('/tmp/enigmastandby', 'wb').close()
		except:
			log.write("Failed to create /tmp/enigmastandby")
	else:
		try:
			os.remove("/tmp/enigmastandby")
		except:
			pass
	# now reboot
	_session.open(Screens.Standby.TryQuitMainloop, 3)


# Autostart section

class AutoStartTimer:
	def __init__(self, session):
		self.session = session
		self.prev_onlybouquet = config.plugins.epgimport.import_onlybouquet.value
		self.prev_multibouquet = config.usage.multibouquet.value
		self.clock = config.plugins.epgimport.wakeup.value
		self.autoStartImport = eTimer()
		if isDreambox:
			self.autoStartImport_conn = self.autoStartImport.timeout.connect(self.onTimer)
		else:
			self.autoStartImport.callback.append(self.onTimer)
		self.pauseAfterFinishImportCheck = eTimer()
		if isDreambox:
			self.pauseAfterFinishImportCheck_conn = self.pauseAfterFinishImportCheck.timeout.connect(self.afterFinishImportCheck)
		else:
			self.pauseAfterFinishImportCheck.callback.append(self.afterFinishImportCheck)
		self.pauseAfterFinishImportCheck.startLongTimer(30)
		self.container = None
		self.update()

	def getWakeTime(self):
		if config.plugins.epgimport.enabled.value:
			clock = config.plugins.epgimport.wakeup.value
			nowt = time.time()
			now = time.localtime(nowt)
			return int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, clock[0], clock[1], lastMACbyte() // 5, 0, now.tm_yday, now.tm_isdst)))
		else:
			return -1

	def update(self, atLeast=0):
		self.autoStartImport.stop()
		wake = self.getWakeTime()
		now_t = time.time()
		now = int(now_t)
		now_day = time.localtime(now_t)
		if wake > 0:
			cur_day = int(now_day.tm_wday)
			wakeup_day = WakeupDayOfWeek()
			if wakeup_day == -1:
				return -1
				log.write("[EPGImport] wakeup day of week disabled")
			if wake < now + atLeast:
				wake += 86400 * wakeup_day
			else:
				if not config.plugins.extra_epgimport.day_import[cur_day].value:
					wake += 86400 * wakeup_day
			next = wake - now
			self.autoStartImport.startLongTimer(next)
		else:
			wake = -1
		log.write("[EPGImport] WakeUpTime now set to %s (now=%s)" % (
			time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(wake)) if wake > 0 else "Not Set",
			time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
		))
		return wake

	def runImport(self):
		if self.prev_onlybouquet != config.plugins.epgimport.import_onlybouquet.value or self.prev_multibouquet != config.usage.multibouquet.value:
			self.prev_onlybouquet = config.plugins.epgimport.import_onlybouquet.value
			self.prev_multibouquet = config.usage.multibouquet.value
			EPGConfig.channelCache = {}
		cfg = EPGConfig.loadUserSettings()
		sources = [s for s in EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"])]
		if sources:
			sources.reverse()
			epgimport.sources = sources
			startImport()

	def onTimer(self):
		self.autoStartImport.stop()
		now = int(time.time())
		log.write("[EPGImport] onTimer occurred at %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)))
		wake = self.getWakeTime()
		# If we're close enough, we're okay...
		atLeast = 0
		if wake - now < 60:
			self.runImport()
			atLeast = 60
		self.update(atLeast)

	def getSources(self):
		cfg = EPGConfig.loadUserSettings()
		sources = [s for s in EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"])]
		if sources:
			return True
		return False

	def getStatus(self):
		wake_up = self.getWakeTime()
		now_t = time.time()
		now = int(now_t)
		now_day = time.localtime(now_t)
		if wake_up > 0:
			cur_day = int(now_day.tm_wday)
			wakeup_day = WakeupDayOfWeek()
			if wakeup_day == -1:
				log.write("[EPGImport] wakeup day of week disabled")
				return -1

			if wake_up < now:
				wake_up += 86400 * wakeup_day
			else:
				if not config.plugins.extra_epgimport.day_import[cur_day].value:
					wake_up += 86400 * wakeup_day
		else:
			wake_up = -1
		return wake_up

	def afterFinishImportCheck(self):
		if config.plugins.epgimport.deepstandby.value == 'wakeup' and getFPWasTimerWakeup():
			if os.path.exists("/tmp/enigmastandby") or os.path.exists("/tmp/.EPGImportAnswerBoot"):
				log.write("[EPGImport] is restart enigma2")
			else:
				wake = self.getStatus()
				now_t = time.time()
				now = int(now_t)
				if 0 < wake - now <= 60 * 5:
					if config.plugins.epgimport.standby_afterwakeup.value:
						if not Screens.Standby.inStandby:
							Notifications.AddNotification(Screens.Standby.Standby)
							log.write("[EPGImport] Run to standby after wake up")
					if config.plugins.epgimport.shutdown.value:
						if not config.plugins.epgimport.standby_afterwakeup.value:
							if not Screens.Standby.inStandby:
								Notifications.AddNotification(Screens.Standby.Standby)
								log.write("[EPGImport] Run to standby after wake up for checking")
						if not config.plugins.epgimport.deepstandby_afterimport.value:
							config.plugins.epgimport.deepstandby_afterimport.value = True
							self.wait_timer = eTimer()
							if isDreambox:
								self.wait_timer_conn = self.wait_timer.timeout.connect(self.startStandby)
							else:
								self.wait_timer.callback.append(self.startStandby)
							print("[EPGImport] start wait_timer (10sec) for goto standby")
							self.wait_timer.start(10000, True)

	def startStandby(self):
		if Screens.Standby.inStandby:
			log.write("[EPGImport] add checking standby")
			try:
				Screens.Standby.inStandby.onClose.append(self.onLeaveStandby)
			except:
				pass

	def onLeaveStandby(self):
		if config.plugins.epgimport.deepstandby_afterimport.value:
			config.plugins.epgimport.deepstandby_afterimport.value = False
			log.write("[EPGImport] checking standby remove, not deep standby after import")


def WakeupDayOfWeek():
	start_day = -1
	try:
		now = time.time()
		now_day = time.localtime(now)
		cur_day = int(now_day.tm_wday)
	except:
		cur_day = -1
	if cur_day >= 0:
		for i in (1, 2, 3, 4, 5, 6, 7):
			if config.plugins.extra_epgimport.day_import[(cur_day + i) % 7].value:
				return i
	return start_day


def onBootStartCheck():
	global autoStartTimer
	log.write("[EPGImport] onBootStartCheck")
	now = int(time.time())
	wake = autoStartTimer.getStatus()
	log.write("[EPGImport] now=%d wake=%d wake-now=%d" % (now, wake, wake - now))
	if (wake < 0) or (wake - now > 600):
		on_start = False
		if config.plugins.epgimport.runboot.value == "1":
			on_start = True
			log.write("[EPGImport] is boot")
		elif config.plugins.epgimport.runboot.value == "2" and not getFPWasTimerWakeup():
			on_start = True
			log.write("[EPGImport] is manual boot")
		elif config.plugins.epgimport.runboot.value == "3" and getFPWasTimerWakeup():
			on_start = True
			log.write("[EPGImport] is automatic boot")
		flag = '/tmp/.EPGImportAnswerBoot'
		if config.plugins.epgimport.runboot_restart.value and config.plugins.epgimport.runboot.value != "3":
			if os.path.exists(flag):
				on_start = False
				log.write("[EPGImport] not starting import - is restart enigma2")
			else:
				try:
					open(flag, 'wb').close()
				except:
					log.write("Failed to create /tmp/.EPGImportAnswerBoot")
		if config.plugins.epgimport.runboot_day.value:
			now = time.localtime()
			cur_day = int(now.tm_wday)
			if not config.plugins.extra_epgimport.day_import[cur_day].value:
				on_start = False
				log.write("[EPGImport] wakeup day of week does not match")
		if on_start:
			log.write("[EPGImport] starting import because auto-run on boot is enabled")
			autoStartTimer.runImport()
	else:
		log.write("[EPGImport] import to start in less than 10 minutes anyway, skipping...")


def autostart(reason, session=None, **kwargs):
	"""called with reason=1 to during shutdown, with reason=0 at startup?"""
	global autoStartTimer
	global _session
	log.write("[EPGImport] autostart (%s) occured at (%s)" % (reason, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
	if reason == 0 and _session is None:
		if session is not None:
			_session = session
			if autoStartTimer is None:
				autoStartTimer = AutoStartTimer(session)
			if config.plugins.epgimport.runboot.value != "4":
				onBootStartCheck()
		# If WE caused the reboot, put the box back in standby.
		if os.path.exists("/tmp/enigmastandby"):
			log.write("[EPGImport] Returning to standby")
			if not Screens.Standby.inStandby:
				Notifications.AddNotification(Screens.Standby.Standby)
			try:
				os.remove("/tmp/enigmastandby")
			except:
				pass
	else:
		log.write("[EPGImport] Stop")


def getNextWakeup():
	"""returns timestamp of next time when autostart should be called"""
	if autoStartTimer:
		if config.plugins.epgimport.deepstandby.value == 'wakeup' and autoStartTimer.getSources():
			log.write("[EPGImport] Will wake up from deep sleep")
			return autoStartTimer.getStatus()
	return -1


# we need this helper function to identify the descriptor
def extensionsmenu(session, **kwargs):
	main(session, **kwargs)


def setExtensionsmenu(el):
	try:
		if el.value:
			Components.PluginComponent.plugins.addPlugin(extDescriptor)
		else:
			Components.PluginComponent.plugins.removePlugin(extDescriptor)
	except Exception as e:
		print("[EPGImport] Failed to update extensions menu:", e)


description = _("Automated EPG Importer")
config.plugins.epgimport.showinextensions.addNotifier(setExtensionsmenu, initial_call=False, immediate_feedback=False)
extDescriptor = PluginDescriptor(name=_("EPGImport"), description=description, where=PluginDescriptor.WHERE_EXTENSIONSMENU, fnc=extensionsmenu)
pluginlist = PluginDescriptor(name=_("EPGImport"), description=description, where=PluginDescriptor.WHERE_PLUGINMENU, icon='plugin.png', fnc=main)


def epgmenu(menuid, **kwargs):
	if menuid == "setup":
		return [(_("EPGImport"), main, "epgimporter", 1002)]
	else:
		return []


'''
# PluginDescriptor(
	# name=_("EPGImport"),
	# description=description,
	# where=PluginDescriptor.WHERE_PLUGINMENU,
	# icon='plugin.png',
	# fnc=main
# ),
'''


def Plugins(**kwargs):
	result = [
		PluginDescriptor(
			name="EPGImport",
			description=description,
			where=[
				PluginDescriptor.WHERE_AUTOSTART,
				PluginDescriptor.WHERE_SESSIONSTART
			],
			fnc=autostart,
			wakeupfnc=getNextWakeup
		),
		PluginDescriptor(
			name="EPG importer",
			description=description,
			where=PluginDescriptor.WHERE_MENU,
			fnc=epgmenu  # fnc=main_menu
		),
	]
	if config.plugins.epgimport.showinextensions.value:
		result.append(extDescriptor)
	if config.plugins.epgimport.showinplugins.value:
		result.append(pluginlist)
	return result
