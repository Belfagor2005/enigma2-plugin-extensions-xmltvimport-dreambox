#!/usr/bin/python
# epgdat.py

from enigma import eEPGCache
from ServiceReference import ServiceReference
from Components.config import config
import time


class epgdat_class:

	EPG_HEADER1_channel_count = 0
	EPG_TOTAL_EVENTS = 0
	EXCLUDED_SID = []

	# initialize an empty dictionary (Python array)
	# as channel events container before preprocessing
	events=[]

	def __init__(self, provider_name, provider_priority, epgdb_path=None):
		self.source_name = provider_name
		# get timespan time from system settings defined in days
		# get outdated time from system settings defined in hours
		self.epg_outdated = int(config.epg.histminutes.value)
		# subtract the outdated time from current time
		self.epoch_time = int(time.time()) - (self.epg_outdated * 60)
		# limit (timespan) the number of day to import
		self.epg_timespan = int(config.epg.maxdays.value)
		self.epg_cutoff_time = int(time.time()) + (self.epg_timespan * 86400)
		self.EPG_SKIPPED_EVENTS = 0
		self.start_process()

	def start_process(self):
		self.epgcache = eEPGCache.getInstance()
		return True

	def set_excludedsid(self, exsidlist):
		self.EXCLUDED_SID = exsidlist

	def add_event(self, starttime, duration, title, description, language):
		# ignore language on non DreamOS
		endtime = starttime + duration
		if endtime > self.epoch_time and starttime < self.epg_cutoff_time:
			self.events.append((int(starttime), int(duration), title[:240], title, description, 0))
		else:
			self.EPG_SKIPPED_EVENTS += 1

	def preprocess_events_channel(self, services):
		EPG_EVENT_DATA_id = 0
		events = []
		# now we go through all the channels we got (currently only one)
		for service in services:
			# prepare and write CHANNEL INFO
			channel = ServiceReference(str(service)).getServiceName()
			number_of_events = len(self.events)
			# only add channels where we have events
			if number_of_events > 0:
				self.EPG_HEADER1_channel_count += 1
				events = self.events
				self.epgcache.importEvent(service, events)
				print("[EPGDAT] added %d events for channel %s %s" % (number_of_events, channel, str(service)))
				self.EPG_TOTAL_EVENTS += number_of_events
		# reset event container
		self.events = []

	def cancel_process(self):
		print("[EPGDAT] Importing cancelled")

	def final_process(self):
		print("[EPGDAT] Importing finished and %d events were imported." % (self.EPG_TOTAL_EVENTS))
		print("[EPGDAT] %d Events were outside of the defined timespan((%d minutes outdated and timespan %d days)." % (self.EPG_SKIPPED_EVENTS, self.epg_outdated, self.epg_timespan))
