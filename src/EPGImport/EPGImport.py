#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# This file no longer has a direct link to Enigma2, allowing its use anywhere
# you can supply a similar interface. See plugin.py and OfflineImport.py for
# the contract.

from __future__ import absolute_import
from __future__ import print_function
from Components.config import config
from datetime import datetime
from socket import getaddrinfo, AF_INET6, has_ipv6
from sys import version_info
from twisted import version
from twisted.internet import reactor, threads
from twisted.web.client import downloadPage
import gzip
import os
import random
import sys
import time
import twisted.python.runtime

try:
	pythonVer = sys.version_info.major
except:
	pythonVer = 2


try:  # python3
	from http.client import HTTPException
	from urllib.error import HTTPError, URLError
	# from urllib.parse import urlparse
	from urllib.request import build_opener
except:  # python2
	from httplib import HTTPException
	from urllib2 import build_opener, HTTPError, URLError
	# from urlparse import urlparse


# if pythonVer == 2:
	# import urllib2
	# import httplib
# else:
	# import urllib


# Used to check server validity
date_format = '%Y-%m-%d'
now = datetime.now()
alloweddelta = 2
CheckFile = 'LastUpdate.txt'
ServerStatusList = {}
# MEDIA = ("/media/hdd/", "/media/usb/", "/media/mmc/", "/media/cf/", "/tmp")
PARSERS = {
	'xmltv': 'gen_xmltv',
	'genxmltv': 'gen_xmltv',
}


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
		print("[EPGImport] Errore durante la lettura di /proc/mounts:", e)
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
# config.misc.epgcache_filename.save()


try:
	from twisted.internet import ssl
	from twisted.internet._sslverify import ClientTLSOptions
	sslverify = True
except:
	sslverify = False

if sslverify:
	try:
		from urlparse import urlparse
	except:
		from urllib.parse import urlparse

	class SNIFactory(ssl.ClientContextFactory):
		def __init__(self, hostname=None):
			self.hostname = hostname

		def getContext(self):
			ctx = self._contextFactory(self.method)
			if self.hostname:
				ClientTLSOptions(self.hostname, ctx)
			return ctx


def relImport(name):
	fullname = __name__.split('.')
	fullname[-1] = name
	mod = __import__('.'.join(fullname))
	for n in fullname[1:]:
		mod = getattr(mod, n)
	return mod


def getParser(name):
	module = PARSERS.get(name, name)
	mod = relImport(module)
	return mod.new()


def getTimeFromHourAndMinutes(hour, minute):
	now = time.localtime()
	begin = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hour, minute, 0, now.tm_wday, now.tm_yday, now.tm_isdst)))
	return begin


def bigStorage(minFree, default, *candidates):
	try:
		diskstat = os.statvfs(default)
		free = diskstat.f_bfree * diskstat.f_bsize
		if (free > minFree) and (free > 50000000):
			return default
	except Exception as e:
		print("[bigStorage] Impossibile ottenere informazioni su %s: %s" % (default, e))
	all_mount_points = getMountPoints()
	for candidate in candidates:
		if candidate in all_mount_points:
			try:
				diskstat = os.statvfs(candidate)
				free = diskstat.f_bfree * diskstat.f_bsize
				if free > minFree:
					return candidate
			except Exception as e:
				print("[bigStorage] Impossibile ottenere informazioni su %s: %s" % (candidate, e))
	return default


class OudeisImporter(object):
	"""Wrapper to convert original patch to new one that accepts multiple services"""

	def __init__(self, epgcache):
		self.epgcache = epgcache

	# difference with old patch is that services is a list or tuple, this
	# wrapper works around it.

	def importEvents(self, services, events):
		for service in services:
			self.epgcache.importEvent(service, events)


def unlink_if_exists(filename):
	if filename.endswith("epg.db"):
		return
	try:
		os.unlink(filename)
	except Exception as e:
		print("[EPGImport] warning: Could not remove '%s' intermediate" % filename, repr(e))


class EPGImport(object):
	"""Simple Class to import EPGData"""

	def __init__(self, epgcache, channelFilter):
		self.eventCount = None
		# self.epgcache = None
		self.storage = None
		self.sources = []
		self.source = None
		self.epgsource = None
		self.fd = None
		self.iterator = None
		self.onDone = None
		self.epgcache = epgcache
		self.channelFilter = channelFilter

	def checkValidServer(self, serverurl):
		dirname, filename = os.path.split(serverurl)
		FullString = dirname + '/' + CheckFile
		req = build_opener()
		req.addheaders = [('User-Agent', 'Twisted Client')]
		dlderror = 0
		if dirname in ServerStatusList:
			# If server is know return its status immediately
			return ServerStatusList[dirname]
		else:
			# # Server not in the list so checking it
			# if pythonVer == 2:
			try:
				response = req.open(FullString)
			except HTTPError as e:
				print('[EPGImport] HTTPError in checkValidServer= ' + str(e.code))
				dlderror = 1
			except URLError as e:
				print('[EPGImport] URLError in checkValidServer= ' + str(e.reason))
				dlderror = 1
			except HTTPException as e:
				print('[EPGImport] HTTPException in checkValidServer', e)
				dlderror = 1
			except Exception:
				print('[EPGImport] Generic exception in checkValidServer')
				dlderror = 1

		if not dlderror:
			LastTime = response.read().strip('\n')
			try:
				FileDate = datetime.strptime(LastTime, date_format)
			except ValueError:
				print("[EPGImport] checkValidServer wrong date format in file rejecting server %s" % dirname)
				ServerStatusList[dirname] = 0
				return ServerStatusList[dirname]

			delta = (now - FileDate).days
			if delta <= alloweddelta:
				# OK the delta is in the foreseen windows
				ServerStatusList[dirname] = 1
			else:
				# Sorry the delta is higher removing this site
				print("[EPGImport] checkValidServer rejected server delta days too high: %s" % dirname)
				ServerStatusList[dirname] = 0
		else:
			# We need to exclude this server
			print("[EPGImport] checkValidServer rejected server download error for: %s" % dirname)
			ServerStatusList[dirname] = 0
		return ServerStatusList[dirname]

	def beginImport(self, longDescUntil=None):
		"""Starts importing using Enigma reactor. Set self.sources before calling this."""
		if hasattr(self.epgcache, 'importEvents'):
			self.storage = self.epgcache
		elif hasattr(self.epgcache, 'importEvent'):
			self.storage = OudeisImporter(self.epgcache)
			self.saveEPGCache()
		else:
			print('[EPGImport] oudeis patch not detected, using epg.dat instead.')
			from . import epgdat_importer
			self.storage = epgdat_importer.epgdatclass()
		self.eventCount = 0
		if longDescUntil is None:
			# default to 7 days ahead
			self.longDescUntil = time.time() + 24 * 3600 * 7
		else:
			self.longDescUntil = longDescUntil
		self.nextImport()

	def nextImport(self):
		self.closeReader()
		if not self.sources:
			self.closeImport()
			return
		self.source = self.sources.pop()
		print("[EPGImport] nextImport, source=", self.source.description)
		self.fetchUrl(self.source.url)

	def fetchUrl(self, filename):
		if filename.startswith('http:') or filename.startswith('https:') or filename.startswith('ftp:'):
			self.do_download(filename, self.afterDownload, self.downloadFail)
		else:
			self.afterDownload(None, filename, deleteFile=False)

	def createIterator(self, filename):
		self.source.channels.update(self.channelFilter, filename)
		return getParser(self.source.parser).iterator(self.fd, self.source.channels.items)

	def readEpgDatFile(self, filename, deleteFile=False):
		if not hasattr(self.epgcache, 'load'):
			print("[EPGImport] Cannot load EPG.DAT files on unpatched enigma. Need CrossEPG patch.")
			return
		unlink_if_exists(HDD_EPG_DAT)
		try:
			if filename.endswith('.gz'):
				print("[EPGImport] Uncompressing", filename)
				import shutil
				fd = gzip.open(filename, 'rb')
				epgdat = open(HDD_EPG_DAT, 'wb')
				shutil.copyfileobj(fd, epgdat)
				del fd
				epgdat.close()
				del epgdat
			elif filename != HDD_EPG_DAT:
				os.symlink(filename, HDD_EPG_DAT)
			print("[EPGImport] Importing", HDD_EPG_DAT)
			self.epgcache.load()
			if deleteFile:
				unlink_if_exists(filename)
		except Exception as e:
			print("[EPGImport] Failed to import %s:%s" % (filename, e))

	def afterDownload(self, result, filename, deleteFile=False):
		print("[EPGImport] afterDownload", filename)
		try:
			if not os.path.getsize(filename):
				print("File is empty")
		except Exception as e:
			self.downloadFail(e)
			return

		if self.source.parser == 'epg.dat':
			# if twisted.python.runtime.platform.supportsThreads():
			if False:
				print("[EPGImport] Using twisted thread for DAT file")
				threads.deferToThread(self.readEpgDatFile, filename, deleteFile).addCallback(lambda ignore: self.nextImport())
			else:
				self.readEpgDatFile(filename, deleteFile)
				return
		if filename.endswith('.gz'):
			self.fd = gzip.open(filename, 'rb')
			try:
				# read a bit to make sure it's a gzip file
				self.fd.read(10)
				self.fd.seek(0, 0)
			except Exception as e:
				print("[EPGImport] File downloaded is not a valid gzip file %s" % filename)
				self.downloadFail(e)
				return

		elif filename.endswith('.xz') or filename.endswith('.lzma'):
			try:
				import lzma
			except ImportError:
				from backports import lzma

			self.fd = lzma.open(filename, 'rb')
			try:
				# read a bit to make sure it's an xz file
				self.fd.read(10)
				self.fd.seek(0, 0)

			except Exception as e:
				print("[EPGImport] File downloaded is not a valid xz file %s" % filename)
				self.downloadFail(e)
				return

		else:
			self.fd = open(filename, 'rb')
		if deleteFile and self.source.parser != 'epg.dat':
			try:
				print("[EPGImport] unlink ", filename)
				# if not filename.endswith("epg.db"):
				os.unlink(filename)
			except Exception as e:
				print("[EPGImport] warning: Could not remove '%s' intermediate" % filename, e)

		self.channelFiles = self.source.channels.downloadables()
		if not self.channelFiles:
			self.afterChannelDownload(None, None)
		else:
			filename = random.choice(self.channelFiles)
			self.channelFiles.remove(filename)
			self.do_download(filename, self.afterChannelDownload, self.channelDownloadFail)
		# return

	def afterChannelDownload(self, result, filename, deleteFile=True):
		print("[EPGImport] afterChannelDownload", filename)
		if filename:
			try:
				if not os.path.getsize(filename):
					print("File is empty")
			except Exception as e:
				self.channelDownloadFail(e)
				return

		if twisted.python.runtime.platform.supportsThreads():
			print("[EPGImport] Using twisted thread")
			threads.deferToThread(self.doThreadRead, filename).addCallback(lambda ignore: self.nextImport())
			deleteFile = False  # Thread will delete it
		else:
			self.iterator = self.createIterator(filename)
			reactor.addReader(self)
		if deleteFile and filename:
			try:
				# if not filename.endswith("epg.db"):
				os.unlink(filename)
			except Exception as e:
				print("[EPGImport] warning: Could not remove '%s' intermediate" % filename, e)

	def fileno(self):
		if self.fd is not None:
			return self.fd.fileno()
		else:
			return

	def doThreadRead(self, filename):
		"""This is used on PLi with threading"""
		for data in self.createIterator(filename):
			if data is not None:
				self.eventCount += 1
				try:
					r, d = data
					if d[0] > self.longDescUntil:
						# Remove long description (save RAM memory)
						d = d[:4] + ('',) + d[5:]
					self.storage.importEvents(r, (d,))
				except Exception as e:
					print("[EPGImport] ### importEvents exception:", e)
		print("[EPGImport] ### thread is ready ### Events:", self.eventCount)
		if filename:
			try:
				os.unlink(filename)
			except Exception as e:
				print("[EPGImport] warning: Could not remove '%s' intermediate" % filename, e)

		return

	def doRead(self):
		"""called from reactor to read some data"""
		try:
			# returns tuple (ref, data) or None when nothing available yet.
			# data = self.iterator.next()
			data = next(self.iterator)

			if data is not None:
				self.eventCount += 1
				try:
					r, d = data
					if d[0] > self.longDescUntil:
						# Remove long description (save RAM memory)
						d = d[:4] + ('',) + d[5:]
					self.storage.importEvents(r, (d,))
				except Exception as e:
					print("[EPGImport] importEvents exception:", e)
		except StopIteration:
			self.nextImport()

	def connectionLost(self, failure):
		"""called from reactor on lost connection"""
		# This happens because enigma calls us after removeReader
		print("[EPGImport] connectionLost", failure)

	def channelDownloadFail(self, failure):
		print("[EPGImport] download channel failed:", failure)
		if self.channelFiles:
			filename = random.choice(self.channelFiles)
			self.channelFiles.remove(filename)
			self.do_download(filename, self.afterChannelDownload, self.channelDownloadFail)
		else:
			print("[EPGImport] no more alternatives for channels")
			self.nextImport()

	def downloadFail(self, failure):
		print("[EPGImport] download failed:", failure)
		self.source.urls.remove(self.source.url)
		if self.source.urls:
			print("[EPGImport] Attempting alternative URL")
			self.source.url = random.choice(self.source.urls)
			self.fetchUrl(self.source.url)
		else:
			self.nextImport()

	def logPrefix(self):
		return '[EPGImport]'

	def closeReader(self):
		if self.fd is not None:
			reactor.removeReader(self)
			self.fd.close()
			self.fd = None
			self.iterator = None

	def closeImport(self):
		self.closeReader()
		self.iterator = None
		self.source = None
		if hasattr(self.storage, 'epgfile'):
			needLoad = self.storage.epgfile
		else:
			needLoad = None
		self.storage = None
		if self.eventCount is not None:
			print("[EPGImport] imported %d events" % self.eventCount)
			reboot = False
			if self.eventCount:
				if needLoad:
					print("[EPGImport] no Oudeis patch, load(%s) required" % needLoad)
					reboot = True
					try:
						if hasattr(self.epgcache, 'load'):
							print("[EPGImport] attempt load() patch")
							if needLoad != HDD_EPG_DAT:
								os.symlink(needLoad, HDD_EPG_DAT)
							self.epgcache.load()
							reboot = False
							unlink_if_exists(needLoad)
					except Exception as e:
						print("[EPGImport] load() failed:", e)

				elif hasattr(self.epgcache, 'save'):
					self.epgcache.save()
			elif hasattr(self.epgcache, 'timeUpdated'):
				self.epgcache.timeUpdated()
			if self.onDone:
				self.onDone(reboot=reboot, epgfile=needLoad)
		self.eventCount = None
		print("[EPGImport] #### Finished ####")

	def isImportRunning(self):
		return self.source is not None

	def legacyDownload(self, result, afterDownload, downloadFail, sourcefile, filename, deleteFile=True):
		print("[EPGImport] IPv6 download failed, falling back to IPv4: " + str(sourcefile))
		if sourcefile.startswith("https") and sslverify:
			parsed_uri = urlparse(sourcefile)
			domain = parsed_uri.hostname
			# check for redirects
			try:
				import requests
				r = requests.get(sourcefile, stream=True, timeout=10, verify=False, allow_redirects=True)
				newurl = r.url
				domain = urlparse(newurl).hostname
				newurl = str(newurl)

			except Exception as e:
				print(e)

			sniFactory = SNIFactory(domain)

			if pythonVer == 3:
				newurl = newurl.encode()

			downloadPage(newurl, filename, sniFactory).addCallbacks(afterDownload, downloadFail, callbackArgs=(filename, True))
		else:
			if pythonVer == 3:
				sourcefile = sourcefile.encode()
			downloadPage(sourcefile, filename).addCallbacks(afterDownload, downloadFail, callbackArgs=(filename, True))

	def do_download(self, sourcefile, afterDownload, downloadFail):
		# path = bigStorage(9000000, '/tmp', '/media/DOMExtender', '/media/cf', '/media/mmc', '/media/usb', '/media/hdd')
		path = bigStorage(9000000, *mount_points)
		if not path or not os.path.isdir(path):
			print("[EPGImport] Percorso non valido, usando '/tmp'")
			path = '/tmp'  # Usa un fallback come /tmp se il percorso non è valido.
		if "meia" in path:
			path = path.replace("meia", "media")
		filename = os.path.join(path, 'epgimport')
		ext = os.path.splitext(sourcefile)[1]
		# Keep sensible extension, in particular the compression type
		if ext and len(ext) < 6:
			filename += ext
		# sourcefile = sourcefile.encode('utf-8')
		sourcefile = str(sourcefile)
		print("[EPGImport] Downloading: " + str(sourcefile) + " to local path: " + str(filename))
		ip6 = sourcefile6 = None
		if has_ipv6 and version_info >= (2, 7, 11) and ((version.major == 15 and version.minor >= 5) or version.major >= 16):
			host = sourcefile.split('/')[2]
			# getaddrinfo throws exception on literal IPv4 addresses
			try:
				ip6 = getaddrinfo(host, 0, AF_INET6)
				sourcefile6 = sourcefile.replace(host, '[' + list(ip6)[0][4][0] + ']')
			except:
				pass

		if ip6:
			print("[EPGImport] Trying IPv6 first: " + str(sourcefile6))
			if pythonVer == 3:
				sourcefile6 = sourcefile6.encode()
			downloadPage(sourcefile6, filename, headers={'host': host}).addCallback(afterDownload, filename, True).addErrback(self.legacyDownload, afterDownload, downloadFail, sourcefile, filename, True)

		else:
			print("[EPGImport] No IPv6, using IPv4 directly: " + str(sourcefile))
			if sourcefile.startswith("https") and sslverify:
				parsed_uri = urlparse(sourcefile)
				domain = parsed_uri.hostname

				# check for redirects
				try:
					import requests
					r = requests.get(sourcefile, stream=True, timeout=10, verify=False, allow_redirects=True)
					newurl = r.url
					domain = urlparse(newurl).hostname
					newurl = str(newurl)

				except Exception as e:
					print(e)

				sniFactory = SNIFactory(domain)
				if pythonVer == 3:
					newurl = newurl.encode()

				downloadPage(newurl, filename, sniFactory).addCallbacks(afterDownload, downloadFail, callbackArgs=(filename, True))
			else:
				if pythonVer == 3:
					sourcefile = sourcefile.encode()
				downloadPage(sourcefile, filename).addCallbacks(afterDownload, downloadFail, callbackArgs=(filename, True))
		return filename
