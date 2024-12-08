#!/usr/bin/python

import os
import time
from enigma import eEPGCache, cachestate
from ServiceReference import ServiceReference
from sqlite3 import dbapi2 as sqlite
from Components.config import config
from enigma import eTimer


class epgdb_class:

	EPG_HEADER1_channel_count = 0
	EPG_TOTAL_EVENTS = 0
	EXCLUDED_SID = []

	events = []

	def __init__(self, provider_name, provider_priority, epgdb_path=None, clear_oldepg=False):
		self.source_name = provider_name
		self.priority = provider_priority
		self.epg_outdated = int(config.misc.epgcache_outdated_timespan.value)
		self.epoch_time = int(time.time()) - (self.epg_outdated * 3600)
		self.epg_timespan = int(config.misc.epgcache_timespan.value)
		self.epg_cutoff_time = int(time.time()) + (self.epg_timespan * 86400)
		self.event_counter_journal = 0
		self.events_in_past_journal = 0
		self.events_in_import_range_journal = 0
		self.epgdb_path = config.misc.epgcache_filename.value
		if epgdb_path is None:
			self.epgdb_path = config.misc.epgcache_filename.value
		else:
			self.epgdb_path = epgdb_path
		self.connection = None
		if clear_oldepg:
			self.create_empty()
			self.start_process()
		else:
			self.epginstance = eEPGCache.getInstance()
			self.cacheState_conn = self.epginstance.cacheState.connect(self.cacheStateChanged)
			print("[EPGDB] saving EPG to %s" % self.epgdb_path)
			eEPGCache.save(self.epginstance)

	def cacheStateChanged(self, state):
		if state.state == cachestate.save_finished:
			print("[EPGDB] epgcache save finished")
			self.ProcessingTimer = eTimer()
			if os.path.exists("/var/lib/dpkg/status"):
				self.ProcessingTimer_conn = self.ProcessingTimer.timeout.connect(self.start_process)
			else:
				self.ProcessingTimer.callback.append(self.start_process)
				self.ProcessingTimer.start(10000, True)
#           self.start_process()

	def start_process(self):
		if os.path.exists(self.epgdb_path):
			size = os.path.getsize(self.epgdb_path) / 1024
			# even empty epg.db has at least 23k size
			min_size = 23
			if size < min_size:
				print("[EPGDB] %s too small" % self.epgdb_path)
				return False
		else:
			print("[EPGDB] %s not found" % self.epgdb_path)
			return False
		print("[EPGDB] %s exists" % self.epgdb_path)
		if self.connection is not None:
			print("[EPGDB] %s already connected" % self.epgdb_path)
			return True

		self.events_in_past_journal = 0
		self.events_in_import_range_journal = 0
		self.source_id = None
		try:
			self.connection = sqlite.connect(self.epgdb_path, timeout=20, isolation_level=None, check_same_thread=False)
			self.connection.text_factory = str
			self.cursor = self.connection.cursor()
			# is it really wise for the small performance gain ?
			cmd = "PRAGMA synchronous = OFF"
			self.cursor.execute(cmd)
			cmd = "PRAGMA journal_mode = OFF"
			self.cursor.execute(cmd)
			# check if it is already a valid T_source
			cmd = "SELECT id from T_Source WHERE source_name=? and priority=?"
			self.cursor.execute(cmd, (self.source_name, self.priority))
			row = self.cursor.fetchone()
			if row is not None:
				self.source_id = int(row[0])
				print("[EPGDB] FOUND %s EPG with source_id %d" % (self.source_name, self.source_id))
			else:   # looks like we have to add it
				cmd = "insert into T_Source (source_name, priority) values (?, ?)"
				self.cursor.execute(cmd, (self.source_name, self.priority))
				self.source_id = self.cursor.lastrowid
				self.connection.commit()
				print("[EPGDB] ADDED %s EPG with source_id %d" % (self.source_name, self.source_id))
			# begin transaction  ....
			self.cursor.execute('BEGIN')
			print("[EPGDB] connect to %s finished" % self.epgdb_path)
			return True
		except:
			print("[EPGDB] connect to %s failed" % self.epgdb_path)
			return False

	def set_excludedsid(self, exsidlist):
		self.EXCLUDED_SID = exsidlist

	def add_event(self, starttime, duration, title, description, language):
		self.events.append((starttime, duration, title[:240], description, language))

	def preprocess_events_channel(self, services):
		if self.connection is None:
			print("[EPGDB] not connected, retrying")
			self.start_process()
		# one local cursor per table seems to perform slightly better ...
		cursor_service = self.connection.cursor()
		cursor_event = self.connection.cursor()
		cursor_title = self.connection.cursor()
		cursor_short_desc = self.connection.cursor()
		cursor_extended_desc = self.connection.cursor()
		cursor_data = self.connection.cursor()

		EPG_EVENT_DATA_id = 0
		events = []

		# now we go through all the channels we got
		for service in services:
			channel = ServiceReference(str(service)).getServiceName().encode('ascii', 'ignore')
			if len(channel) == 0:
				channel = str(service)
			ssid = service.split(":")
			number_of_events = len(self.events)
			if number_of_events > 0 and len(ssid) > 6:
				# convert hex stuff to integer as epg.db likes it to have
				self.sid = int(ssid[3], 16)
				self.tsid = int(ssid[4], 16)
				self.onid = int(ssid[5], 16)
				self.dvbnamespace = int(ssid[6], 16)
#               print "[EPGDB] %x %x %x %x" % (self.sid,self.tsid,self.onid,self.dvbnamespace)
				# dvb-t fix: EEEExxxx => EEEE0000
				if self.dvbnamespace > 4008574976 and self.dvbnamespace < 4008636143:
					self.dvbnamespace = 4008574976
				if self.dvbnamespace > 2147483647:
					self.dvbnamespace -= 4294967296

				self.EPG_HEADER1_channel_count += 1

				cmd = "SELECT id from T_Service WHERE sid=? and tsid=? and onid=? and dvbnamespace=?"
				cursor_service.execute(cmd, (self.sid, self.tsid, self.onid, self.dvbnamespace))
				row = cursor_service.fetchone()
				if row is not None:
					self.service_id = int(row[0])
				else:
					cmd = "INSERT INTO T_Service (sid,tsid,onid,dvbnamespace) VALUES(?,?,?,?)"
					cursor_service.execute(cmd, (self.sid, self.tsid, self.onid, self.dvbnamespace))
					self.service_id = cursor_service.lastrowid

				# triggers will clean up the rest ... hopefully ...
				cmd = "DELETE FROM T_Event where service_id=%d" % self.service_id
				cursor_event.execute(cmd)
				# now we go through all the events for this channel/service_id and add them ...
				self.event_counter_journal = 0
				events = self.events
				for event in events:
					# short description (title)
					self.short_d = event[2]
					# extended description
					if len(event[3]) > 0:
						self.long_d = event[3]
					else:
						self.long_d = event[2]
					# extract date and time
					self.begin_time = int(event[0])
					self.duration = int(event[1])
					if self.duration < 1:
						self.duration = 1
					self.language = event[4]
					# we need hash values for descriptions, hash is provided by enigma
					self.short_hash = eEPGCache.getStringHash(self.short_d)
					self.long_hash = eEPGCache.getStringHash(self.long_d)
					# generate an unique dvb event id < 65536
					self.dvb_event_id = (self.begin_time - (self.begin_time / 3932160) * 3932160) / 60
#                   print "[EPGDB] dvb event id: %d" % self.dvb_event_id
					if self.short_hash > 2147483647:
						self.short_hash -= 4294967296
					if self.long_hash > 2147483647:
						self.long_hash -= 4294967296
					# now insert into epg.db what we have
					self.end_time = self.begin_time + self.duration
					if self.end_time > self.epoch_time and self.begin_time < self.epg_cutoff_time and self.source_id is not None:
						cmd = "INSERT INTO T_Event (service_id, begin_time, duration, source_id, dvb_event_id) VALUES(?,?,?,?,?)"
						cursor_event.execute(cmd, (self.service_id, self.begin_time, self.duration, self.source_id, self.dvb_event_id))
						self.event_id = cursor_event.lastrowid
						# check if hash already exists on Title
						cmd = "SELECT id from T_Title WHERE hash=%d" % self.short_hash
						cursor_title.execute(cmd)
						row = cursor_title.fetchone()
						if row is None:
							cmd = "INSERT INTO T_Title (hash, title) VALUES(?,?)"
							cursor_title.execute(cmd, (self.short_hash, self.short_d))
							self.title_id = cursor_title.lastrowid
						else:
							self.title_id = int(row[0])
						cmd = "SELECT id from T_Short_Description WHERE hash=%d" % self.short_hash
						cursor_short_desc.execute(cmd)
						row = cursor_short_desc.fetchone()
						if row is None:
							cmd = "INSERT INTO T_Short_Description (hash, short_description) VALUES(?,?)"
							cursor_short_desc.execute(cmd, (self.short_hash, self.short_d))
							self.short_description_id = cursor_short_desc.lastrowid
						else:
							self.short_description_id = int(row[0])
						# check if hash already exists for Extended Description
						cmd = "SELECT id from T_Extended_Description WHERE hash=%d" % self.long_hash
						cursor_extended_desc.execute(cmd)
						row = cursor_extended_desc.fetchone()
						if row is None:
							cmd = "INSERT INTO T_Extended_Description (hash, extended_description) VALUES(?,?)"
							cursor_extended_desc.execute(cmd, (self.long_hash, self.long_d))
							self.extended_description_id = cursor_extended_desc.lastrowid
						else:
							self.extended_description_id = int(row[0])
						cmd = "INSERT INTO T_Data (event_id, title_id, short_description_id, extended_description_id, iso_639_language_code) VALUES(?,?,?,?,?)"
						cursor_data.execute(cmd, (self.event_id, self.title_id, self.short_description_id, self.extended_description_id, self.language))
						# increase journaling counters
						self.events_in_import_range_journal += 1
						self.event_counter_journal += 1
					else:
						self.events_in_past_journal += 1

			print("[EPGDB] added %d from %d events for channel %s %s" % (self.event_counter_journal, number_of_events, channel, str(service)))
			self.EPG_TOTAL_EVENTS += number_of_events

		# reset event container
		self.events = []
		cursor_service.close()
		cursor_event.close()
		cursor_title.close()
		cursor_short_desc.close()
		cursor_extended_desc.close()
		cursor_data.close()

	def cancel_process(self):
		if self.connection is None:
			print("[EPGDB] still not connected, sorry")
			return
		print("[EPGDB] Importing cancelled")
		self.cursor.execute('END')
		self.cursor.close()
		self.connection.close()
		self.connection = None

	def final_process(self):
		if self.connection is None:
			print("[EPGDB] still not connected, sorry")
			return
		print("[EPGDB] Importing finished. From the total available %d events %d events were imported." % (self.EPG_TOTAL_EVENTS, self.events_in_import_range_journal))
		print("[EPGDB] %d Events were outside of the defined timespan(%d hours outdated and timespan %d days)." % (self.events_in_past_journal, self.epg_outdated, self.epg_timespan))
		try:
			self.cursor.execute('END')
		except:
			pass
		try:
			self.cursor.close()
			self.connection.close()
		except:
			pass
		self.connection = None
		print("[EPGDB] now writes the epg database ...")
		epginstance = eEPGCache.getInstance()
		eEPGCache.load(epginstance)

	def create_empty(self):
		print("[EPGDB] create empty epg.db")
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
