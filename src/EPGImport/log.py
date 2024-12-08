# logging for XMLTV importer
#
# One can simply use
# import log
# print>>log, "Some text"
# because the log unit looks enough like a file!

import sys
from cStringIO import StringIO
import threading
import os
logfile = StringIO()
# Need to make our operations thread-safe.
mutex = threading.Lock()


def write(data):
    '''
    with mutex:
        Check if the log exceeds 8 KB
        if logfile.tell() > 100000:
            # Move the pointer to the beginning
            logfile.seek(0)
            logfile.truncate(0)  # Clear the buffer
        logfile.write(data)
        logfile.write('\n')
    sys.stdout.write(data)
    '''
    with mutex:
        if logfile.tell() > 1000000:  # 1 MB
            logfile.close()
            backup_name = logfile.name + ".bak"
            if os.path.exists(backup_name):
                i = 1
                while os.path.exists(backup_name + "." + str(i)):
                    i += 1
                backup_name = backup_name + "." + str(i)
            os.rename(logfile.name, backup_name)
            # logfile = open(logfile.name, 'w')
            logfile.write("Logfile rotated\n")
        logfile.write(data)
        logfile.write('\n')
        try:
            sys.stdout.write(data + '\n')
        except Exception as e:
            sys.stderr.write("Error writing to stdout: " + str(e) + '\n')


def getvalue():
    with mutex:
        if logfile.closed:
            print("The log file is closed and cannot be read.")
        # # Capture the current position
        # # pos = logfile.tell()
        logfile.seek(0)  # Move to the start of the buffer
        head = logfile.read()  # Read the entire buffer
        logfile.seek(0)  # Reset to the start
        return head
