# -*- coding: utf-8 -*-

from __future__ import print_function

from xml.etree.cElementTree import iterparse
from calendar import timegm
from time import strptime, struct_time
# import six
from . import log
from HTMLParser import HTMLParser
html_parser = HTMLParser()

try:
	basestring
except NameError:
	basestring = str


def quickptime(date_str):
	return struct_time(
		(
			int(date_str[0:4]),     # Year
			int(date_str[4:6]),     # Month
			int(date_str[6:8]),     # Day
			int(date_str[8:10]),    # Hour
			int(date_str[10:12]),   # Minute
			0,                      # Second (set to 0)
			-1,                     # Weekday (set to -1 as unknown)
			-1,                     # Julian day (set to -1 as unknown)
			0                       # DST (Daylight Saving Time, set to 0 as unknown)
		)
	)


def get_time_utc(timestring, fdateparse):
	"""
	Converts a timestring with an offset into UTC time.
	Args:
		timestring: A string in the format "YYYYMMDDhhmmss +HHMM" or similar.
		fdateparse: A function to parse the date portion of the timestring.
	Returns:
		The UTC time as a Unix timestamp or None in case of an error.
	"""
	try:
		values = timestring.split(" ")
		tm = fdateparse(values[0])
		time_gm = timegm(tm)
		# suppose file says +0300 => that means we have to substract 3 hours from localtime to get GMT
		if len(values) > 1:
			timezone_offset_str = values[1]  # +0100
			# Extract the numeric part of the time zone
			timezone_offset = int(timezone_offset_str[:3])  # Extract the first 3 characters (+01)
			time_gm -= (timezone_offset * 3600)
		return time_gm
	except Exception as e:
		print("[XMLTVConverter] get_time_utc error:", e)
		return 0


# Preferred language should be configurable, but for now,
# we just like Dutch better!


def get_xml_string(elem, name):
	r = ""
	try:
		for node in elem.findall(name):
			txt = node.text
			lang = node.get("lang", None)
			if not r:
				r = txt
			elif lang == "nl":
				r = txt
	except Exception as e:
		print("[XMLTVConverter] get_xml_string error:{}".format(e))
	# Now returning UTF-8 by default, the epgdat/oudeis must be adjusted to make this work.
	r = html_parser.unescape(r)
	return r.encode('utf-8')


def get_xml_language(elem, name):
	r = ''
	lang_map = {
		"ar": "ara",  # Arabic
		"az": "aze",  # Azerbaijani
		"bg": "bul",  # Bulgarian
		"bn": "ben",  # Bengali
		"bs": "bos",  # Bosnian
		"cs": "ces",  # Czech (ISO 639-2/T), "cze" is bibliographic
		"da": "dan",  # Danish
		"de": "deu",  # German
		"dk": "dan",  # Danish (non standard)
		"el": "gre",  # Greek (bibliographic), "ell" (terminologic ISO 639-2/T)
		"en": "eng",  # English
		"es": "spa",  # Spanish
		"et": "est",  # Estonian
		"fa": "per",  # Persian (bibliographic), "fas" for ISO 639-2/T
		"fi": "fin",  # Finnish
		"fr": "fra",  # French
		"he": "heb",  # Hebrew
		"hi": "hin",  # Hindi
		"hr": "hrv",  # Croatian
		"hu": "hun",  # Hungarian
		"hy": "hye",  # Armenian (ISO 639-2/T), "arm" is bibliographic
		"id": "ind",  # Indonesian
		"is": "isl",  # Icelandic (ISO 639-2/T), "ice" is bibliographic
		"it": "ita",  # Italian
		"ja": "jpn",  # Japanese
		"ka": "kat",  # Georgian (ISO 639-2/T), "geo" is bibliographic
		"ko": "kor",  # Korean
		"lb": "ltz",  # Luxembourgish
		"lt": "lit",  # Lithuanian
		"lv": "lav",  # Latvian
		"mk": "mkd",  # Macedonian (ISO 639-2/T), "mac" is bibliographic
		"ml": "mal",  # Malayalam
		"ms": "msa",  # Malay
		"mt": "mlt",  # Maltese
		"nb": "nob",  # Norwegian Bokmål
		"nl": "nld",  # Dutch (new ISO) - "dut" is old ISO 639-2/B
		"nn": "nno",  # Norwegian Nynorsk
		"no": "nor",  # Norwegian
		"pl": "pol",  # Polish
		"pt": "por",  # Portuguese
		"ro": "ron",  # Romanian (ron is ISO 639-2/T) "rum" is bibliographic
		"ru": "rus",  # Russian
		"se": "sme",  # Northern Sami
		"sk": "slk",  # Slovak (ISO 639-2/T), "slo" is bibliographic
		"sl": "slv",  # Slovenian
		"sq": "sqi",  # Albanian (ISO 639-2/T), "alb" is bibliographic
		"sr": "srp",  # Serbian
		"sv": "swe",  # Swedish
		"ta": "tam",  # Tamil
		"te": "tel",  # Telugu
		"th": "tha",  # Thai
		"tr": "tur",  # Turkish
		"uk": "ukr",  # Ukrainian
		"ur": "urd",  # Urdu
		"vi": "vie",  # Vietnamese
		"zh": "chi",  # Chinese (bibliographic), "zho" for ISO 639-2/T
	}
	try:
		for node in elem.findall(name):
			lang = node.get("lang", None)
			if not r:
				# use mapping dictionary instead of if-elif
				r = lang_map.get(lang, "eng")
	except Exception as e:
		print("[XMLTVConverter] get_xml_language error:{}".format(e))
	return r.encode('utf-8')


def enumerateProgrammes(fp):
	"""Enumerates programme ElementTree nodes from file object 'fp'"""
	for event, elem in iterparse(fp):
		if elem.tag == "programme":
			yield elem
			elem.clear()
		elif elem.tag == "channel":
			# Throw away channel elements, save memory
			elem.clear()


class XMLTVConverter:
	def __init__(self, channels_dict, category_dict, dateformat="%Y%m%d%H%M%S %Z"):
		self.channels = channels_dict
		self.categories = category_dict
		if dateformat.startswith("%Y%m%d%H%M%S"):
			self.dateParser = quickptime
		else:
			self.dateParser = lambda x: strptime(x, dateformat)

	def enumFile(self, fileobj):
		log.write("[XMLTVConverter] Enumerating event information\n")
		lastUnknown = None
		# there is nothing no enumerate if there are no channels loaded
		if not self.channels:
			return
		for elem in enumerateProgrammes(fileobj):
			channel = elem.get("channel")
			channel = channel.lower()
			if channel not in self.channels:
				if lastUnknown != channel:
					log.write("Unknown channel: {0}\n".format(channel))
					lastUnknown = channel
				# return a None object to give up time to the reactor.
				yield None
				continue
			try:
				services = self.channels[channel]
				start = get_time_utc(elem.get("start"), self.dateParser)
				stop = get_time_utc(elem.get("stop"), self.dateParser)
				title = get_xml_string(elem, "title")
				try:  # Adding map with language
					lang_code = get_xml_language(elem, "title") or get_xml_language(elem, "desc") or "eng"
					language = [(lang_code, int(lang_code) - 3)]
				except:
					language = None
				# Check duration to ensure it's a number
				duration = stop - start
				if not isinstance(duration, int):
					log.write("[XMLTVConverter] Invalid duration format: {0}\n".format(duration))
					continue  # Skip this entry if duration is not an integer

				# Try/except for EPG XML files with program entries containing <sub-title ... />
				try:
					subtitle = get_xml_string(elem, "sub-title")
				except:
					subtitle = ""

				# Try/except for EPG XML files with program entries containing <desc ... />
				try:
					description = get_xml_string(elem, "desc")
				except:
					description = ""
				category = get_xml_string(elem, "category")
				if not category:  # Check if category is empty
					category = "Unknown"  # Assign a default category if empty
				cat_nr = self.get_category(category, duration)

				if not stop or not start or (stop <= start):
					print("[XMLTVConverter] Bad start/stop time: %s (%s) - %s (%s) [%s]" % (elem.get('start'), start, elem.get('stop'), stop, title))

				if language:
					yield (services, (start, stop - start, title, subtitle, description, cat_nr, 0, language))
				else:
					yield (services, (start, stop - start, title, subtitle, description, cat_nr))

			except Exception as e:
				print("[XMLTVConverter] parsing event error:", e)

	# edit for add new category in dictionary
	def get_category(self, cat, duration):
		if (not cat) or (not isinstance(cat, type("str"))):
			return 0
		categories = cat.split(',')
		for category in categories:
			category = category.strip()
			if category in self.categories:
				category_value = self.categories[category]
				if len(category_value) > 1:
					if duration > 60 * category_value[1]:
						return category_value[0]
				elif len(category_value) > 0:
					return category_value[0]
		return 0
