
# Python 2/3 compatibility imports
from __future__ import print_function

# standard library imports
import json  # for working with data file
from threading import Thread
from time import sleep
import os
from datetime import datetime

# local module imports
from blinker import signal
import gv  # Get access to SIP's settings
from sip import template_render  #  Needed for working with web.py templates
from urls import urls  # Get access to SIP's URLs
import web  # web.py framework
from webpages import ProtectedPage

try:
    from db_logger import db_logger_read_definitions
    from db_logger_generic_table import create_generic_table, add_date_generic_table
    withDBLogger = True
except ImportError:
    withDBLogger = False


# Add new URLs to access classes in this plugin.
# fmt: off
urls.extend([
    u"/advance-pump-set", u"plugins.advance_pump.settings",
    u"/advance-pump-set-save", u"plugins.advance_pump.save_settings",
    u"/advance-pump-home", u"plugins.advance_pump.home",
    ])
# fmt: on

# Add this plugin to the PLUGINS menu ["Menu Name", "URL"], (Optional)
gv.plugin_menu.append([_(u"Advance Pump"), u"/advance-pump-home"])

settingsAdvancePump = {}

# Read in the commands for this plugin from it's JSON file
def load_advance_pump():
    global settingsAdvancePump

    try:
        with open(u"./data/advance_pump.json", u"r") as f:  # Read settings from json file if it exists
            settingsAdvancePump = json.load(f)
    except IOError:  # If file does not exist return empty value
        # write default values to files
        with open(u"./data/advance_pump.json", u"w") as f:  # Edit: change name of json file
                json.dump(settingsAdvancePump, f)  # save to file

class home(ProtectedPage):
    """
    Load an html page for entering plugin settings.
    """

    def GET(self):
        settings = {}
        return template_render.advance_pump_home(settings)  # open settings page

class settings(ProtectedPage):
    """
    Load an html page for entering plugin settings.
    """

    def GET(self):
        settings = {}
        return template_render.advance_pump(settings)  # open settings page

