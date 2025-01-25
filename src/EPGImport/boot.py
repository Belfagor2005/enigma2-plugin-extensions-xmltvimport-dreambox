#!/usr/bin/python
# -*- coding: utf-8 -*-

from Components.config import config
import os
import shutil
import time

MEDIA = ("/media/hdd/", "/media/usb/", "/media/mmc/", "/media/cf/", "/tmp")


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


def findEpg():
	candidates = []
	for path in MEDIA:
		try:
			if os.path.exists(path):
				for fn in os.listdir(path):
					if "epg.dat" in fn:
						ffn = os.path.join(path, fn)
						candidates.append((os.path.getctime(ffn), ffn))
		except:
			pass  # ignore errors.
	if not candidates:
		return None
	candidates.sort()  # order by ctime...
	# best candidate is most recent filename.
	return candidates[-1][1]


for mp in mount_points:
	epg_path = os.path.join(mp, 'epg.dat')
	if os.path.exists(epg_path):
		mount_point = epg_path
		break


def checkCrashLog():
	for path in mount_points[:-1]:
		try:
			dirList = os.listdir(path)
			for fname in dirList:
				if fname[0:13] == 'enigma2_crash':
					try:
						crashtime = 0
						crashtime = int(fname[14:24])
						howold = time.time() - crashtime
					except:
						print("no time found in filename")
					if howold < 120:
						print("recent crashfile found analysing")
						crashfile = open(path + fname, "r")
						crashtext = crashfile.read()
						crashfile.close()
						if (crashtext.find("FATAL: LINE ") != -1):
							print("string found, deleting epg.dat")
							return True
		except:
			pass
	return False


def findNewEpg():
	for mp in mount_points:
		newepg_path = os.path.join(mp, 'epg_new.dat')
		if os.path.exists(newepg_path):
			return newepg_path
	return None


epg = '/etc/enigma2/epg.dat'
newepg = findNewEpg()

if config.misc.epgcache_filename.value:
	epg = config.misc.epgcache_filename.value
else:
	config.misc.epgcache_filename.setValue(epg)
print("Epg.dat found at : ", epg)
print("newepg  found at : ", newepg)

# Delete epg.dat if last crash was because of error in epg.dat
if checkCrashLog():
	try:
		os.unlink(epg)
	except:
		print("delete error")

# if excists cp epg_new.dat epg.dat
if newepg:
	if epg:
		print("replacing epg.dat with newmade version")
		os.unlink(epg)
		shutil.copy2(newepg, epg)
