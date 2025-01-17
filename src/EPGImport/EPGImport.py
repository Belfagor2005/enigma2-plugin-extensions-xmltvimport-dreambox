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
from twisted.internet import reactor, ssl, threads
from twisted.web.client import downloadPage
import gzip
import os
import random
import time
import twisted.python.runtime
import shutil
from . import log

try:  # python3
    from http.client import HTTPException
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlparse
    from urllib.request import build_opener
except:  # python2
    from httplib import HTTPException
    from urllib2 import build_opener, HTTPError, URLError
    from urlparse import urlparse


try:
    pythonVer = version_info.major
except:
    pythonVer = 2


# Funzione alternativa per random.choices
def random_choices(population, k=1):
    if hasattr(random, 'choices'):  # Se random.choices è disponibile (Python 3.6+)
        return random.choices(population, k=k)
    else:  # Compatibilità con Python 2 (o versioni precedenti di Python 3)
        return [random.choice(population) for _ in range(k)]


try:
    from twisted.internet._sslverify import ClientTLSOptions
    from twisted.internet import ssl
    sslverify = True
except:
    sslverify = False

if sslverify:

    class SNIFactory(ssl.ClientContextFactory):
        def __init__(self, hostname=None):
            self.hostname = hostname

        def getContext(self):
            ctx = self._contextFactory(self.method)
            if self.hostname:
                ClientTLSOptions(self.hostname, ctx)
            return ctx


# Used to check server validity
date_format = "%Y-%m-%d"
now = datetime.now()
alloweddelta = 2
CheckFile = "LastUpdate.txt"
ServerStatusList = {}

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
        print("[EPGImport] Error reading /proc/mounts:", e)
    return mount_points


mount_points = getMountPoints()
mount_point = None
for mp in mount_points:
    epg_path = os.path.join(mp, 'epg.dat')
    if os.path.exists(epg_path):
        mount_point = epg_path
        break


HDD_EPG_DAT = '/etc/enigma2/epg.dat'

if config.misc.epgcache_filename.value:
    HDD_EPG_DAT = config.misc.epgcache_filename.value
else:
    config.misc.epgcache_filename.setValue(HDD_EPG_DAT)


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
    if not (0 <= hour < 24):
        raise ValueError("Hour must be between 0 and 23")
    if not (0 <= minute < 60):
        raise ValueError("Minute must be between 0 and 59")
    now = time.localtime()
    begin = int(time.mktime((now.tm_year, now.tm_mon, now.tm_mday,
                hour, minute, 0, now.tm_wday, now.tm_yday, now.tm_isdst)))
    return begin


def bigStorage(minFree, default, *candidates):
    try:
        diskstat = os.statvfs(default)
        free = diskstat.f_bfree * diskstat.f_bsize
        if (free > minFree) and (free > 50000000):
            return default
    except Exception as e:
        print("[EPGImport][bigStorage] Failed to stat %s:" % default, e)
    all_mount_points = getMountPoints()
    for candidate in candidates:
        if candidate in all_mount_points:
            try:
                diskstat = os.statvfs(candidate)
                free = diskstat.f_bfree * diskstat.f_bsize
                if free > minFree:
                    return candidate
            except Exception as e:
                print("[EPGImport][bigStorage] Failed to stat %s:" % candidate, e)
                continue
    return default


class OudeisImporter:
    """Wrapper to convert original patch to new one that accepts multiple services"""

    def __init__(self, epgcache):
        self.epgcache = epgcache

    # difference with old patch is that services is a list or tuple, this
    # wrapper works around it.

    def importEvents(self, services, events):
        for service in services:
            try:
                self.epgcache.importEvent(service, events)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print("[EPGImport][OudeisImporter][importEvents] ### importEvents exception:", e)


def unlink_if_exists(filename):
    try:
        os.unlink(filename)
    except Exception as e:
        print("[EPGImport] warning: Could not remove '%s' intermediate" % filename, repr(e))


class EPGImport:
    """Simple Class to import EPGData"""

    def __init__(self, epgcache, channelFilter):
        self.eventCount = None
        self.epgcache = None
        self.storage = None
        self.sources = []
        self.source = None
        self.epgsource = None
        self.fd = None
        self.iterator = None
        self.onDone = None
        self.epgcache = epgcache
        self.channelFilter = channelFilter
        return

    def checkValidServer(self, serverurl):
        print("[EPGImport][checkValidServer]checkValidServer serverurl %s" % serverurl)
        dirname, filename = os.path.split(serverurl)
        FullString = dirname + "/" + CheckFile
        req = build_opener()
        req.addheaders = [('User-Agent', 'Twisted Client')]
        dlderror = 0
        if dirname in ServerStatusList:
            # If server is know return its status immediately
            return ServerStatusList[dirname]
        else:
            # Server not in the list so checking it
            try:
                response = req.open(FullString, timeout=5)
            except HTTPError as e:
                print('[EPGImport][checkValidServer] HTTPError in checkValidServer= ' + str(e.code))
                dlderror = 1
            except URLError as e:
                print('[EPGImport][checkValidServer] URLError in checkValidServer= ' + str(e.reason))
                dlderror = 1
            except HTTPException as e:
                print('[EPGImport][checkValidServer] HTTPException in checkValidServer', e)
                dlderror = 1
            except Exception:
                print('[EPGImport][checkValidServer] Generic exception in checkValidServer')
                dlderror = 1

            if not dlderror:
                LastTime = response.read()
                if isinstance(LastTime, bytes):  # Verifica se è un oggetto bytes
                    LastTime = LastTime.decode("utf-8", "ignore").strip('\n')  # Decodifica i bytes in stringa
                try:
                    FileDate = datetime.strptime(LastTime, date_format)
                except ValueError:
                    print("[EPGImport][checkValidServer] checkValidServer wrong date format in file rejecting server %s" % dirname)
                    ServerStatusList[dirname] = 0
                    response.close()
                    return ServerStatusList[dirname]
                delta = (now - FileDate).days
                if delta <= alloweddelta:
                    ServerStatusList[dirname] = 1
                else:
                    print("[EPGImport][checkValidServer] checkValidServer rejected server delta days too high: %s" % dirname)
                    ServerStatusList[dirname] = 0
                response.close()
            else:
                print("[EPGImport][checkValidServer] checkValidServer rejected server download error for: %s" % dirname)
                ServerStatusList[dirname] = 0
        return ServerStatusList[dirname]

    def beginImport(self, longDescUntil=None):
        """Starts importing using Enigma reactor. Set self.sources before calling this."""
        if hasattr(self.epgcache, 'importEvents'):
            self.storage = self.epgcache
        elif hasattr(self.epgcache, 'importEvent'):
            self.storage = OudeisImporter(self.epgcache)
        else:
            print("[EPGImport][beginImport] oudeis patch not detected, using epg.dat instead.")
            from . import epgdat_importer
            self.storage = epgdat_importer.epgdatclass()
        self.eventCount = 0
        if longDescUntil is None:
            # default to 7 days ahead
            self.longDescUntil = time.time() + 24 * 3600 * 7
        else:
            self.longDescUntil = longDescUntil
        self.nextImport()
        return

    def nextImport(self):
        self.closeReader()
        if not self.sources:
            self.closeImport()
            return
        self.source = self.sources.pop()
        print("[EPGImport][nextImport], source=", self.source.description, file=log)
        self.fetchUrl(self.source.url)

    def fetchUrl(self, filename):
        if isinstance(filename, list):
            if len(filename) > 0:
                filename = filename[0]
            else:
                self.downloadFail("Empty list of alternative URLs", None)
                return
        if filename.startswith('http:') or filename.startswith('https:') or filename.startswith('ftp:'):
            print("Attempting to download from: %s" % filename)
            self.do_download(filename, self.afterDownload, self.downloadFail)
        else:
            self.afterDownload(None, filename, deleteFile=False)
        return

    def createIterator(self, filename):
        self.source.channels.update(self.channelFilter, filename)
        return getParser(self.source.parser).iterator(self.fd, self.source.channels.items)

    def readEpgDatFile(self, filename, deleteFile=False):
        if not hasattr(self.epgcache, 'load'):
            print("[EPGImport][readEpgDatFile] Cannot load EPG.DAT files on unpatched enigma. Need CrossEPG patch.", file=log)
            return
        unlink_if_exists(HDD_EPG_DAT)
        try:
            if filename.endswith('.gz'):
                print("[EPGImport][readEpgDatFile] Uncompressing", filename, file=log)
                fd = gzip.open(filename, 'rb')
                epgdat = open(HDD_EPG_DAT, 'wb')
                shutil.copyfileobj(fd, epgdat)
                del fd
                epgdat.close()
                del epgdat
            elif filename != HDD_EPG_DAT:
                os.symlink(filename, HDD_EPG_DAT)
            print("[EPGImport][readEpgDatFile] Importing", HDD_EPG_DAT, file=log)
            self.epgcache.load()
            if deleteFile:
                unlink_if_exists(filename)
        except Exception as e:
            print("[EPGImport][readEpgDatFile] Failed to import %s:" % filename, e, file=log)

    def afterDownload(self, result, filename, deleteFile=False):
        print("[EPGImport] afterDownload", filename, file=log)
        """
        if not os.path.exists(filename):
            self.downloadFail("File not exists")
            return
        """
        try:
            if not os.path.getsize(filename):
                print("File is empty")
        except Exception as e:
            self.downloadFail(e)
            return

        if self.source.parser == 'epg.dat':
            if twisted.python.runtime.platform.supportsThreads():
                print("[EPGImport][afterDownload] Using twisted thread for DAT file", file=log)
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
                print("[EPGImport][afterDownload] File downloaded is not a valid gzip file", filename, file=log)
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
                print("[EPGImport][afterDownload] File downloaded is not a valid xz file", filename, file=log)
                self.downloadFail(e)
                return

        else:
            self.fd = open(filename, 'rb')
        if deleteFile and self.source.parser != 'epg.dat':
            try:
                print("[EPGImport][afterDownload] unlink", filename, file=log)
                os.unlink(filename)
            except Exception as e:
                print("[EPGImport][afterDownload] warning: Could not remove '%s' intermediate" % filename, e, file=log)

        self.channelFiles = self.source.channels.downloadables()
        if not self.channelFiles:
            self.afterChannelDownload(None, None)
        else:
            filename = random.choice(self.channelFiles)
            # filename = random_choices(self.channelFiles)
            self.channelFiles.remove(filename)
            self.do_download(filename, self.afterChannelDownload, self.channelDownloadFail)
        return

    def afterChannelDownload(self, result, filename, deleteFile=True):
        print("[EPGImport][afterChannelDownload] filename", filename, file=log)
        if filename:
            try:
                if not os.path.getsize(filename):
                    print("File is empty")
            except Exception as e:
                print("[EPGImport][afterChannelDownload] Exception filename", filenamele=log)
                self.channelDownloadFail(e)
                return

        if twisted.python.runtime.platform.supportsThreads():
            print("[EPGImport][afterChannelDownload] Using twisted thread - filename ", file=log)
            threads.deferToThread(self.doThreadRead, filename).addCallback(lambda ignore: self.nextImport())
            deleteFile = False  # Thread will delete it
        else:
            self.iterator = self.createIterator(filename)
            reactor.addReader(self)
        if deleteFile and filename:
            try:
                os.unlink(filename)
            except Exception as e:
                print("[EPGImport][afterChannelDownload] warning: Could not remove '%s' intermediate" % filename, e, file=log)

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
                    if len(data) >= 2:
                        r, d = data
                        if d[0] > self.longDescUntil:
                            # Remove long description (save RAM memory)
                            d = d[:4] + ('',) + d[5:]
                        self.storage.importEvents(r, (d,))
                    else:
                        print("[EPGImport][doRead] Warning: tuple data has less than 2 elements", file=log)
                except Exception as e:
                    print("[EPGImport][doThreadRead] ### importEvents exception:", e, file=log)
        print("[EPGImport][doThreadRead] ### thread is ready ### Events:", self.eventCount, file=log)
        if filename:
            try:
                os.unlink(filename)
            except Exception as e:
                print("[EPGImport][doThreadRead] warning: Could not remove '%s' intermediate" % filename, e, file=log)

        return

    def doRead(self):
        """called from reactor to read some data"""
        try:
            # returns tuple (ref, data) or None when nothing available yet.
            data = next(self.iterator)

            if data is not None:
                self.eventCount += 1
                try:
                    # Make sure that date has at least 2 elements
                    if len(data) >= 2:
                        r, d = data
                        if d[0] > self.longDescUntil:
                            # Remove long description (save RAM memory)
                            d = d[:4] + ('',) + d[5:]
                        self.storage.importEvents(r, (d,))
                    else:
                        print("[EPGImport][doRead] Warning: tuple data has less than 2 elements", file=log)
                except Exception as e:
                    print("[EPGImport][doRead] importEvents exception:", e, file=log)

        except StopIteration:
            self.nextImport()

        return

    def connectionLost(self, failure):
        """called from reactor on lost connection"""
        # This happens because enigma calls us after removeReader
        print("[EPGImport][connectionLost]", failure, file=log)

    def channelDownloadFail(self, failure):
        print("[EPGImport][connectionLost]download channel failed:", failure, file=log)
        if self.channelFiles:
            filename = random.choice(self.channelFiles)
            # filename = random_choices(self.channelFiles)
            self.channelFiles.remove(filename)
            self.do_download(filename, self.afterChannelDownload, self.channelDownloadFail)
        else:
            print("[EPGImport] no more alternatives for channels", file=log)
            self.nextImport()

    def downloadFail(self, failure):
        print("[EPGImport][DownloadFail]download failed:", failure, file=log)
        self.source.urls.remove(self.source.url)
        if self.source.urls:
            print("[EPGImport][DownloadFail]Attempting alternative URL", file=log)
            self.source.url = random.choice(self.source.urls)
            # self.source.url = random_choices(self.source.urls)
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
        return

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
            print("[EPGImport] imported %d events" % self.eventCount, file=log)
            reboot = False
            if self.eventCount:
                if needLoad:
                    print("[EPGImport] no Oudeis patch, load(%s) required" % needLoad, file=log)
                    reboot = True
                    try:
                        if hasattr(self.epgcache, 'load'):
                            print("[EPGImport] attempt load() patch", file=log)
                            if needLoad != HDD_EPG_DAT:
                                os.symlink(needLoad, HDD_EPG_DAT)
                            self.epgcache.load()
                            reboot = False
                            unlink_if_exists(needLoad)
                    except Exception as e:
                        print("[EPGImport] load() failed:", e, file=log)

                elif hasattr(self.epgcache, 'save'):
                    self.epgcache.save()
            elif hasattr(self.epgcache, 'timeUpdated'):
                self.epgcache.timeUpdated()
            if self.onDone:
                self.onDone(reboot=reboot, epgfile=needLoad)
        self.eventCount = None
        print("[EPGImport] #### Finished ####", file=log)
        return

    def isImportRunning(self):
        return self.source is not None

    def legacyDownload(self, result, afterDownload, downloadFail, sourcefile, filename, deleteFile=True):
        print("[EPGImport] IPv6 download failed, falling back to IPv4: " + str(sourcefile), file=log)
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
        sourcefile = str(sourcefile)
        print("[EPGImport][do_download] Downloading: " + str(sourcefile) + " to local path: " + str(filename), file=log)

        ip6 = sourcefile6 = None
        if has_ipv6 and version_info >= (2, 7, 11) and ((version.major == 15 and version.minor >= 5) or version.major >= 16):
            host = sourcefile.split('/')[2]
            # getaddrinfo throws exception on literal IPv4 addresses
            try:
                ip6 = getaddrinfo(host, 0, AF_INET6)
                sourcefile6 = sourcefile.replace(host, '[' + list(ip6)[0][4][0] + ']')
            except Exception as e:
                print("[EPGImport][do_download] IPv6 not available: " + str(e))
        sslcf = SNIFactory(sourcefile) if sourcefile.startswith('https:') else None

        if ip6:
            print("[EPGImport][do_download] Trying IPv6 first: " + sourcefile6)
            if pythonVer == 3:
                sourcefile6 = sourcefile6.encode()
            downloadPage(sourcefile6, filename, contextFactory=sslcf).addCallback(afterDownload, filename, True).addErrback(self.legacyDownload, afterDownload, downloadFail, sourcefile, filename, True)

        else:
            print("[EPGImport][do_download] No IPv6, using IPv4 directly: " + str(sourcefile), file=log)
            if sourcefile.startswith("https") and sslverify:
                try:
                    # Controlla i redirect con `requests`
                    import requests
                    r = requests.get(sourcefile, stream=True, timeout=10, verify=False, allow_redirects=True)
                    sourcefile = r.url
                    print("[EPGImport] URL aggiornato dopo redirect: " + sourcefile)
                except Exception as e:
                    print("[EPGImport][do_download] Errore durante il controllo dei redirect: " + str(e))

                parsed_uri = urlparse(sourcefile)
                domain = parsed_uri.hostname
                sniFactory = SNIFactory(domain)
                if pythonVer == 3:
                    sourcefile = sourcefile.encode()

                downloadPage(sourcefile, filename, contextFactory=sniFactory).addCallbacks(afterDownload, downloadFail, callbackArgs=(filename, True))

            else:
                if pythonVer == 3:
                    sourcefile = sourcefile.encode()
                downloadPage(sourcefile, filename).addCallbacks(afterDownload, downloadFail, callbackArgs=(filename, True))
        return filename
