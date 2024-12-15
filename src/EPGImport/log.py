# logging for XMLTV importer
#
# One can simply use
# import log
# print>>log, "Some text"
# because the log unit looks enough like a file!

import sys
from cStringIO import StringIO
import threading

logfile = StringIO()
# Need to make our operations thread-safe.
mutex = threading.Lock()


def write(data):
	mutex.acquire()
	try:
		if logfile.tell() > 1000000:
			logfile.reset()
		logfile.write(data)
	finally:
		mutex.release()
	sys.stdout.write(data)


def getvalue():
	mutex.acquire()
	try:
		pos = logfile.tell()
		head = logfile.read()
		logfile.reset()
		tail = logfile.read(pos)
	finally:
		mutex.release()
	return head + tail
