#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
****************************************
*        coded by Lululla              *
*             15/02/2025               *
****************************************
# Info corvoboys.org
"""

from os import listdir, makedirs, chdir, remove, walk
from os.path import join, isdir, exists
from shutil import rmtree, copyfileobj, copytree, copy2
import tarfile
import ssl


def make_dirs(directory):
	"""Create directory if it does not exist (compatible with Python 2 and 3)."""
	try:
		makedirs(directory)
	except OSError:
		if not isdir(directory):
			raise


try:
	import urllib.request as urllib_request  # Python 3

	def url_open(url, context):
		return urllib_request.urlopen(url, context=context)
except ImportError:
	import urllib2 as urllib_request  # Python 2

	def url_open(url, context):
		return urllib_request.urlopen(url)  # No context in Python 2


def copytree_compat(src, dst):
	"""Copy tree with Python 2 and 3 compatibility."""
	if exists(dst):
		rmtree(dst, ignore_errors=True)
	copytree(src, dst)


def main(url):
	TMPSources = "/var/volatile/tmp/EPGimport-Sources-main"
	dest_dir = "/etc/epgimport"
	SETTINGS_FILE = "/etc/enigma2/epgimport.conf"

	make_dirs(TMPSources)
	make_dirs(dest_dir)

	chdir(TMPSources)
	tarball = "main.tar.gz"
	context = ssl._create_unverified_context()

	response = None
	try:
		response = url_open(url, context)
		with open(tarball, "wb") as out_file:
			copyfileobj(response, out_file)
	finally:
		if response:
			response.close()

	# Remove existing files in dest_dir before extracting
	for item in listdir(dest_dir):
		item_path = join(dest_dir, item)
		if isdir(item_path):
			rmtree(item_path, ignore_errors=True)
		else:
			remove(item_path)

	try:
		with tarfile.open(tarball, "r:gz") as tar:
			for member in tar.getmembers():
				tar.extract(member, path=TMPSources)
	except tarfile.TarError:
		print("Error extracting tar file")
		return

	extracted_dir = join(TMPSources, "EPGimport-Sources-main")

	for root, _, files in walk(extracted_dir):
		for file in files:
			if file.endswith(".bb"):
				remove(join(root, file))

	for item in listdir(extracted_dir):
		src_item = join(extracted_dir, item)
		if isdir(src_item):
			copytree_compat(src_item, join(dest_dir, item))
		else:
			copy2(src_item, dest_dir)

	rmtree(TMPSources, ignore_errors=True)
	if exists(SETTINGS_FILE):
		remove(SETTINGS_FILE)

	try:
		from os import sync
		sync()
	except ImportError:
		pass


# if __name__ == "__main__":
	# url = "https://github.com/Belfagor2005/EPGimport-Sources/archive/refs/heads/main.tar.gz"
	# main(url)
