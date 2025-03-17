#!/usr/bin/python
# -*- coding: utf-8 -*-

from . import _
from . import EPGConfig
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Sources.List import List
from enigma import eServiceReference, eServiceCenter, getDesktop
from Screens.ChannelSelection import service_types_radio, service_types_tv, ChannelSelectionBase
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from ServiceReference import ServiceReference
import os

FHD = True if getDesktop(0).size().width() == 1920 else False
OFF = 0
EDIT_BOUQUET = 1
EDIT_ALTERNATIVES = 2


def getProviderName(ref):
	typestr = ref.getData(0) in (2, 10) and service_types_radio or service_types_tv
	pos = typestr.rfind(":")
	rootstr = "%s (channelID == %08x%04x%04x) && %s FROM PROVIDERS ORDER BY name" % (typestr[:pos + 1], ref.getUnsignedData(4), ref.getUnsignedData(2), ref.getUnsignedData(3), typestr[pos + 1:])
	provider_root = eServiceReference(rootstr)
	serviceHandler = eServiceCenter.getInstance()
	providerlist = serviceHandler.list(provider_root)
	if providerlist is not None:
		while True:
			provider = providerlist.getNext()
			if not provider.valid():
				break
			if provider.flags & eServiceReference.isDirectory:
				servicelist = serviceHandler.list(provider)
				if servicelist is not None:
					while True:
						service = servicelist.getNext()
						if not service.valid():
							break
						if service == ref:
							info = serviceHandler.info(provider)
							return info and info.getName(provider) or "Unknown"
	return ""


class FiltersList():
	def __init__(self):
		self.services = []
		self.load()

	def loadFrom(self, filename):
		try:
			with open(filename, "r") as cfg:
				for line in cfg:
					if line[0] in "#;\n":
						continue
					ref = line.strip()
					if ref not in self.services:
						self.services.append(ref)
		except Exception as e:
			print("FiltersList error:", e)

	def saveTo(self, filename):
		try:
			if not os.path.isdir("/etc/epgimport"):
				os.system("mkdir /etc/epgimport")
			cfg = open(filename, "w")
		except:
			return
		for ref in self.services:
			cfg.write("%s\n" % (ref))
		cfg.close()

	def load(self):
		self.loadFrom("/etc/epgimport/ignore.conf")

	def reload(self):
		self.services = []
		self.load()

	def servicesList(self):
		return self.services

	def save(self):
		self.saveTo("/etc/epgimport/ignore.conf")

	def addService(self, ref):
		if isinstance(ref, str) and ref not in self.services:
			self.services.append(ref)

	def addServices(self, services):
		if isinstance(services, list):
			for s in services:
				if s not in self.services:
					self.services.append(s)

	def delService(self, ref):
		if isinstance(ref, str) and ref in self.services:
			self.services.remove(ref)

	def delAll(self):
		self.services = []
		self.save()


filtersServicesList = FiltersList()


class filtersServicesSetup(Screen):
	if FHD:
		skin = """
		<screen name="filtersServicesSetup" position="center,center" size="1200,820" title="Ignore services list">
			<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="295,70" />
			<ePixmap pixmap="skin_default/buttons/green.png" position="305,5" size="295,70" />
			<ePixmap pixmap="skin_default/buttons/yellow.png" position="600,5" size="295,70" />
			<ePixmap pixmap="skin_default/buttons/blue.png" position="895,5" size="295,70" />
			<widget backgroundColor="#9f1313" font="Regular;30" halign="center" position="10,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_red" transparent="1" valign="center" zPosition="1" />
			<widget backgroundColor="#1f771f" font="Regular;30" halign="center" position="305,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_green" transparent="1" valign="center" zPosition="1" />
			<widget backgroundColor="#a08500" font="Regular;30" halign="center" position="600,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_yellow" transparent="1" valign="center" zPosition="1" />
			<widget backgroundColor="#18188b" font="Regular;30" halign="center" position="895,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_blue" transparent="1" valign="center" zPosition="1" />
			<eLabel backgroundColor="grey" position="10,80" size="1180,1" />
			<widget enableWrapAround="1" source="list" render="Listbox" position="10,90" scrollbarMode="showOnDemand" size="1180,721">
				<convert type="TemplatedMultiContent">
					{"template": [
						MultiContentEntryText(pos=(10,3),size=(1160,35),font=0,flags=RT_HALIGN_LEFT,text=0),
						MultiContentEntryText(pos=(10,40),size=(1160,32),font=1,flags=RT_HALIGN_LEFT,text=1),
						MultiContentEntryText(pos=(10,72),size=(1160,30),font=2,flags=RT_HALIGN_LEFT,text=2),],
					"fonts":[gFont("Regular",30),gFont("Regular",26),gFont("Regular",24)],
					"itemHeight":103}
				</convert>
			</widget>
			<eLabel backgroundColor="grey" position="10,730" size="1260,1" />
			<widget name="introduction" position="20,750" size="1240,50" font="Regular;24" halign="center" valign="center" />
		</screen>"""
	else:
		skin = """
		<screen name="filtersServicesSetup" position="center,center" size="820,520" title="Ignore services list">
			<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="200,50" scale="stretch"/>
			<ePixmap pixmap="skin_default/buttons/green.png" position="210,5" size="200,50" scale="stretch"/>
			<ePixmap pixmap="skin_default/buttons/yellow.png" position="410,5" size="200,50" scale="stretch"/>
			<ePixmap pixmap="skin_default/buttons/blue.png" position="610,5" size="200,50" scale="stretch"/>
			<widget name="key_red" position="10,5" size="200,50" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
			<widget name="key_green" position="210,5" size="200,50" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
			<widget name="key_yellow" position="410,5" size="200,50" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#a08500" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
			<widget name="key_blue" position="610,5" size="200,50" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#18188b" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
			<eLabel position="10,60" size="800,1" backgroundColor="grey"/>
			<widget enableWrapAround="1" source="list" render="Listbox" position="10,65" size="800,450" scrollbarMode="showOnDemand" >
				<convert type="TemplatedMultiContent">
					{"template": [
					MultiContentEntryText(pos=(10,2),size=(780,27),font=0,flags=RT_HALIGN_LEFT,text=0),
					MultiContentEntryText(pos=(10,30),size=(780,22),font=1,flags=RT_HALIGN_LEFT,text=1),
					MultiContentEntryText(pos=(10,52),size=(780,20),font=2,flags=RT_HALIGN_LEFT,text=2),],
						"fonts":[gFont("Regular",22),gFont("Regular",18),gFont("Regular",16)],
						"itemHeight":75}
				</convert>
			</widget>
			<eLabel position="10,460" size="800,1" backgroundColor="grey" />
			<widget name="introduction" position="10,475" size="800,30" font="Regular;20" halign="center" valign="center" />
		</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.RefList = filtersServicesList
		self.prev_list = self.RefList.services[:]

		self["list"] = List([])
		self.updateList()

		self["key_red"] = Label(" ")
		self["key_green"] = Label(_("Add Provider"))
		self["key_yellow"] = Label(_("Add Channel"))
		self["key_blue"] = Label(" ")
		self["introduction"] = Label(_("press OK to save list"))
		self.updateButtons()
		self["actions"] = ActionMap(
			[
				"OkCancelActions",
				"ColorActions"
			],
			{
				"cancel": self.exit,
				"ok": self.keyOk,
				"red": self.keyRed,
				"green": self.keyGreen,
				"yellow": self.keyYellow,
				"blue": self.keyBlue
			},
			-1
		)
		self.setTitle(_("Ignore services list(press OK to save)"))

	def keyRed(self):
		cur = self["list"].getCurrent()
		if cur and len(cur) > 2:
			self.RefList.delService(cur[2])
			self.updateList()
			self.updateButtons()

	def keyGreen(self):
		self.session.openWithCallback(self.addServiceCallback, filtersServicesSelection, providers=True)

	def keyYellow(self):
		self.session.openWithCallback(self.addServiceCallback, filtersServicesSelection)

	def addServiceCallback(self, *service):
		if service:
			ref = service[0]
			if isinstance(ref, list):
				self.RefList.addServices(ref)
			else:
				refstr = ":".join(ref.toString().split(":")[:11])
				if any(x in refstr for x in ("1:0:", "4097:0:", "5001:0:", "5002:0:")):
					self.RefList.addService(refstr)
			self.updateList()
			self.updateButtons()

	def keyBlue(self):
		if len(self.list):
			self.session.openWithCallback(self.removeCallback, MessageBox, _("Really delete all list?"), MessageBox.TYPE_YESNO)

	def removeCallback(self, answer):
		if answer:
			self.RefList.delAll()
			self.updateList()
			self.updateButtons()
			self.prev_list = self.RefList.services[:]

	def keyOk(self):
		self.RefList.save()
		if self.RefList.services != self.prev_list:
			self.RefList.reload()
			EPGConfig.channelCache = {}
		self.close()

	def exit(self):
		self.RefList.services = self.prev_list
		self.RefList.save()
		self.close()

	def updateList(self):
		self.list = []
		for service in self.RefList.servicesList():
			if any(x in service for x in ("1:0:", "4097:0:", "5001:0:", "5002:0:")):
				provname = getProviderName(eServiceReference(service))
				servname = ServiceReference(service).getServiceName() or "N/A"
				self.list.append((servname, provname, service))
		self["list"].setList(self.list)
		self["list"].updateList(self.list)

	def updateButtons(self):
		if len(self.list):
			self["key_red"].setText(_("Delete selected"))
			self["key_blue"].setText(_("Delete all"))
		else:
			self["key_red"].setText(" ")
			self["key_blue"].setText(" ")


class filtersServicesSelection(ChannelSelectionBase):
	if FHD:
		skin = """
		<screen position="center,center" size="1200,820" title="Channel Selection">
		<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="295,70" />
		<ePixmap pixmap="skin_default/buttons/green.png" position="305,5" size="295,70" />
		<ePixmap pixmap="skin_default/buttons/yellow.png" position="600,5" size="295,70" />
		<ePixmap pixmap="skin_default/buttons/blue.png" position="895,5" size="295,70" />
		<widget backgroundColor="#9f1313" font="Regular;30" halign="center" position="10,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_red" transparent="1" valign="center" zPosition="1" />
		<widget backgroundColor="#1f771f" font="Regular;30" halign="center" position="305,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_green" transparent="1" valign="center" zPosition="1" />
		<widget backgroundColor="#a08500" font="Regular;30" halign="center" position="600,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_yellow" transparent="1" valign="center" zPosition="1" />
		<widget backgroundColor="#18188b" font="Regular;30" halign="center" position="895,5" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2" size="295,70" name="key_blue" transparent="1" valign="center" zPosition="1" />
		<eLabel backgroundColor="grey" position="10,80" size="1180,1" />
		<widget enableWrapAround="1" name="list" position="10,90" scrollbarMode="showOnDemand" serviceItemHeight="60" size="1180,720" />
		</screen>
		"""
	else:
		skin = """
		<screen position="center,center" size="820,520" title="Channel Selection">
		<ePixmap pixmap="skin_default/buttons/red.png" position="10,5" size="200,40"/>
		<ePixmap pixmap="skin_default/buttons/green.png" position="210,5" size="200,40"/>
		<ePixmap pixmap="skin_default/buttons/yellow.png" position="410,5" size="200,40"/>
		<ePixmap pixmap="skin_default/buttons/blue.png" position="610,5" size="200,40"/>
		<widget name="key_red" position="10,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#9f1313" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
		<widget name="key_green" position="210,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#1f771f" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
		<widget name="key_yellow" position="410,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#a08500" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
		<widget name="key_blue" position="610,5" size="200,40" zPosition="1" font="Regular;20" halign="center" valign="center" backgroundColor="#18188b" transparent="1" foregroundColor="white" shadowColor="black" shadowOffset="-2,-2"/>
		<eLabel position="10,50" size="800,1" backgroundColor="grey"/>
		<widget name="list" position="10,60" size="800,408" enableWrapAround="1" scrollbarMode="showOnDemand"/>
		</screen>
		"""

	def __init__(self, session, providers=False):
		self.providers = providers
		ChannelSelectionBase.__init__(self, session)
		self.bouquet_mark_edit = OFF
		self.setTitle(_("Channel Selection"))
		self["actions"] = ActionMap(["OkCancelActions", "TvRadioActions"], {"cancel": self.close, "ok": self.channelSelected, "keyRadio": self.setModeRadio, "keyTV": self.setModeTv})
		self.onLayoutFinish.append(self.setModeTv)

	def channelSelected(self):
		ref = self.getCurrentSelection()
		if self.providers and (ref.flags & 7) == 7:
			if "provider" in ref.toString():
				menu = [(_("All services provider"), "providerlist")]

				def addAction(choice):
					if choice is not None:
						if choice[1] == "providerlist":
							serviceHandler = eServiceCenter.getInstance()
							servicelist = serviceHandler.list(ref)
							if servicelist is not None:
								providerlist = []
								while True:
									service = servicelist.getNext()
									if not service.valid():
										break
									refstr = ":".join(service.toString().split(":")[:11])
									providerlist.append((refstr))
								if providerlist:
									self.close(providerlist)
								else:
									self.close(None)
				self.session.openWithCallback(addAction, ChoiceBox, title=_("Select action"), list=menu)
			else:
				self.enterPath(ref)
		elif (ref.flags & 7) == 7:
			self.enterPath(ref)
		elif "provider" not in ref.toString() and not self.providers and not (ref.flags & (64 | 128)) and "%3a//" not in ref.toString():
			if ref.valid():
				self.close(ref)

	def setModeTv(self):
		self.setTvMode()
		if self.providers:
			self.showProviders()
		else:
			self.showFavourites()

	def setModeRadio(self):
		self.setRadioMode()
		if self.providers:
			self.showProviders()
		else:
			self.showFavourites()
