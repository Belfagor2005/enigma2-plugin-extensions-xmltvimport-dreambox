#!/usr/bin/python
# -*- coding: utf-8 -*-

from Components.config import config

global filterCustomChannel

# if config.plugins.epgimport.filter_custom_channel.value:
    # filterCustomChannel = True
# else:
    # filterCustomChannel = False
    
# Verifica che la configurazione epgimport sia definita
if hasattr(config.plugins, "epgimport") and hasattr(config.plugins.epgimport, "filter_custom_channel"):
    filterCustomChannel = config.plugins.epgimport.filter_custom_channel.value
else:
    filterCustomChannel = False  # Fallback se non è definito
