# logging for XMLTV importer
#
# One can simply use
# import log
# print>>log, "Some text"
# because the log unit looks enough like a file!

import sys
import threading

try:  # python2 only
	from cStringIO import StringIO
except:  # both python2 and python3
	from io import StringIO

logfile = StringIO()
mutex = threading.Lock()

def write(data):
    with mutex:
        # Check if the log exceeds 500kb
        if logfile.tell() > 500000:
            # Move the pointer to the beginning
            logfile.seek(0)
            logfile.truncate(0)  # Clear the buffer
        logfile.write(data)
        logfile.write('\n')
    sys.stdout.write(data)

def getvalue():
    with mutex:
        # Capture the current position
        # pos = logfile.tell()
        logfile.seek(0)  # Move to the start of the buffer
        head = logfile.read()  # Read the entire buffer
        logfile.seek(0)  # Reset to the start
        return head
