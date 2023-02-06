
# Python 2/3 compatibility imports
from __future__ import print_function

# standard library imports
import json  # for working with data file
from threading import Thread, Lock
from time import sleep
import copy
from datetime import datetime

# request HTTP
import requests

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
    u"/advance-pump-delete", u"plugins.advance_pump.delete_pump",
    ])
# fmt: on

# Add this plugin to the PLUGINS menu ["Menu Name", "URL"], (Optional)
gv.plugin_menu.append([_(u"Advance Pump"), u"/advance-pump-home"])

settingsAdvancePump = {'PumpName': [], 'PumpDeviceType': [], 'PumpIP': [], 'PumpNeedValves': [], 'PumpNeedValvesOn': [], 'PumpNeedValvesOff': [], 'PumpKeepState': []}
mutexAdvPump = Lock()

def pupmpAction(deviceType : str, pumpIP : str, setState : bool):
    resposeIsOk = -1

    if deviceType == 'shelly1':
        if setState:
            commandURL = u"http://" + pumpIP + u"/relay/0?turn=on"
        else:
            commandURL = u"http://" + pumpIP + u"/relay/0?turn=off"
        response = None

        try:
            response = requests.get(commandURL)
            resposeIsOk = 0

            response = response.json()
        except requests.exceptions.Timeout:
            # Maybe set up for a retry, or continue in a retry loop
            resposeIsOk = 1
            print("Connection time out")
        except requests.exceptions.TooManyRedirects:
            # Tell the user their URL was bad and try a different one
            resposeIsOk = 2
            print("Too many redirections")
        except requests.exceptions.RequestException as e:
            # catastrophic error. bail.
            #raise SystemExit(e)
            resposeIsOk = 3
            print("Fatal error")
    else:
        pass
        # TODO: another supported device

    return resposeIsOk

def runTreadPump():
    global settingsAdvancePump, mutexAdvPump, pumpsStateVect

    mutexAdvPump.acquire()
    lastPupState = copy.deepcopy(pumpsStateVect)
    mutexAdvPump.release()

    lastTime = datetime.datetime.now()

    while True:
        sleep(1)
        listPups2TurnOn = []
        listPups2TurnOff = []

        listPups2KeepOn = []
        listPups2KeepOff = []

        mutexAdvPump.acquire()
        localSettings = copy.deepcopy(settingsAdvancePump)

        # for new pupms fix the state
        if len(pumpsStateVect) > len(lastPupState):
            for newPump in range(pumpsStateVect):
                if pumpsStateVect[newPump]:
                    listPups2TurnOn.append(newPump)
                else:
                    listPups2TurnOff.append(newPump)

        for currentPumpId in range(min(len(pumpsStateVect), len(lastPupState))):
            if pumpsStateVect[currentPumpId]:
                if pumpsStateVect[currentPumpId] != lastPupState[currentPumpId]:
                    listPups2TurnOn.append(currentPumpId)
                else:
                    listPups2KeepOn.append(currentPumpId)
            else:
                if pumpsStateVect[currentPumpId] != lastPupState[currentPumpId]:
                    listPups2TurnOff.append(currentPumpId)
                else:
                    listPups2KeepOff.append(currentPumpId)

        # save last pupms stats, to check changes
        lastPupState = copy.deepcopy(pumpsStateVect)
        mutexAdvPump.release()

        # send signal to station that change
        for pupmpIdOn in listPups2TurnOn:
            if pupmpIdOn < len(localSettings):
                pupmpAction(localSettings['PumpDeviceType'][pupmpIdOn], localSettings['PumpIP'][pupmpIdOn], True)

        # TODO: every 30 seconds force state if needed and check if valves are only
        nowTime = datetime.datetime.now()
        diffTime = nowTime - lastTime
        secondsInt = int(diffTime.seconds)
        if 30 - secondsInt > 0:
            lastTime = nowTime

            # send signal to all pumps to keep on
            for currPumpKeepOnId in listPups2KeepOn:
                if localSettings['PumpKeepState'][currPumpKeepOnId]:
                    pupmpAction(localSettings['PumpDeviceType'][currPumpKeepOnId], localSettings['PumpIP'][currPumpKeepOnId], True)

            # send signal to all pumps to keep off
            for currPumpKeepOffId in listPups2KeepOn:
                if localSettings['PumpKeepState'][currPumpKeepOffId]:
                    pupmpAction(localSettings['PumpDeviceType'][currPumpKeepOffId], localSettings['PumpIP'][currPumpKeepOffId], False)

# Read in the commands for this plugin from it's JSON file
def load_advance_pump():
    global settingsAdvancePump, mutexAdvPump, pumpsStateVect

    mutexAdvPump.acquire()

    try:
        with open(u"./data/advance_pump.json", u"r") as f:  # Read settings from json file if it exists
            settingsAdvancePump = json.load(f)
    except IOError:  # If file does not exist return empty value
        # write default values to files
        with open(u"./data/advance_pump.json", u"w") as f:  # Edit: change name of json file
                json.dump(settingsAdvancePump, f)  # save to file

    pumpsStateVect = [False] * len(settingsAdvancePump['PumpName'])

    mutexAdvPump.release()

    # tread to check if pupm is on-line
    threadMain = Thread(target = runTreadPump)
    threadMain.start()

load_advance_pump()

#### output command when signal received ####
def on_zone_change_pump(name, **kw):
    global pumpsStateVect, mutexAdvPump

    """ Send command when core program signals a change in station state."""
    mutexAdvPump.acquire()    

    for pumpId in range(len(settingsAdvancePump['PumpName'])):
        anyValveNeedPump = False

        # check if any valve need pump working to have water
        for valveIdNeedPump in settingsAdvancePump['PumpNeedValves'][pumpId]:
            if valveIdNeedPump < len(gv.srvals) and gv.srvals[valveIdNeedPump]:
                anyValveNeedPump = True

        # check if every valves are open to flow wather when pump is working
        for valveIdNeedOnPump in settingsAdvancePump['PumpNeedValvesOn'][pumpId]:
            if valveIdNeedOnPump < len(gv.srvals) and not gv.srvals[valveIdNeedOnPump]:
                anyValveNeedPump = False

        # check if every valves are close to flow wather when pump is working
        for valveIdNeedOffPump in settingsAdvancePump['PumpNeedValvesOff'][pumpId]:
            if valveIdNeedOffPump < len(gv.srvals) and not gv.srvals[valveIdNeedOffPump]:
                anyValveNeedPump = False

        pumpsStateVect[pumpId] = anyValveNeedPump

    mutexAdvPump.release()
    return

zones = signal(u"zone_change")
zones.connect(on_zone_change_pump)

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
        global settingsAdvancePump

        qdict = web.input()

        addPump = 0
        if "AddPumps" in qdict:
            addPump = int(qdict["AddPumps"])

        return template_render.advance_pump(settingsAdvancePump, addPump)  # open settings page

class save_settings(ProtectedPage):
    """
    Load an html page for entering plugin settings.
    """

    def GET(self):
        global settingsAdvancePump, pumpsStateVect

        mutexAdvPump.acquire()
        settingsAdvancePumpTMP = copy.deepcopy(settingsAdvancePump)
        mutexAdvPump.release()

        qdict = web.input()

        initialSize = len(settingsAdvancePumpTMP['PumpName'])

        # Get name of pupms
        for pumpId in range(initialSize + 1):
            if "pumpName" + str(pumpId) in qdict:
                if pumpId < initialSize:
                    settingsAdvancePumpTMP['PumpName'][pumpId] = qdict["pumpName" + str(pumpId)]
                else:
                    settingsAdvancePumpTMP['PumpName'].append(qdict["pumpName" + str(pumpId)])

        # pump device type
        for pumpId in range(initialSize + 1):
            if "deviceType" + str(pumpId) in qdict:
                if pumpId < initialSize:
                    settingsAdvancePumpTMP['PumpDeviceType'][pumpId] = qdict["deviceType" + str(pumpId)]
                else:
                    settingsAdvancePumpTMP['PumpDeviceType'].append(qdict["deviceType" + str(pumpId)])

        # Get pump IP
        for pumpId in range(initialSize + 1):
            if "deviceIP" + str(pumpId) in qdict:
                if pumpId < initialSize:
                    settingsAdvancePumpTMP['PumpIP'][pumpId] = qdict["deviceIP" + str(pumpId)]
                else:
                    settingsAdvancePumpTMP['PumpIP'].append(qdict["deviceIP" + str(pumpId)])

        # check if pupm to keep state
        for pumpId in range(initialSize + 1):
            if pumpId < initialSize:
                settingsAdvancePumpTMP['PumpKeepState'][pumpId] = "deviceForceState" + str(pumpId) in qdict
            else:
                settingsAdvancePumpTMP['PumpKeepState'].append("deviceForceState" + str(pumpId) in qdict)


        # Get list of valves need of working of pump
        for pumpId in range(initialSize + 1):
            listValves = []
            for bid in range(0,gv.sd['nbrd']):
                for s in range(0,8):
                    sid = bid*8 + s
                    if 'valvesNeedPump' + str(pumpId) + 'Valve' + str(sid) in qdict:
                        # valve must be active
                        listValves.append(sid)
            if pumpId < initialSize:
                # update exist
                settingsAdvancePumpTMP['PumpNeedValves'][pumpId] = listValves
            else:
                # add new
                settingsAdvancePumpTMP['PumpNeedValves'].append(listValves)

        # anly allow pump work if valve is on
        for pumpId in range(initialSize + 1):
            listValves = []
            for bid in range(0,gv.sd['nbrd']):
                for s in range(0,8):
                    sid = bid*8 + s
                    if 'valvesNeedPump' + str(pumpId) + 'ON' + str(sid) in qdict:
                        # valve must be active
                        listValves.append(sid)
            if pumpId < initialSize:
                # update exist
                settingsAdvancePumpTMP['PumpNeedValvesOn'][pumpId] = listValves
            else:
                # add new
                settingsAdvancePumpTMP['PumpNeedValvesOn'].append(listValves)

        # anly allow pump work if valve is off
        for pumpId in range(initialSize + 1):
            listValves = []
            for bid in range(0,gv.sd['nbrd']):
                for s in range(0,8):
                    sid = bid*8 + s
                    if 'valvesNeedPump' + str(pumpId) + 'Off' + str(sid) in qdict:
                        # valve must be active
                        listValves.append(sid)
            if pumpId < initialSize:
                # update exist
                settingsAdvancePumpTMP['PumpNeedValvesOff'][pumpId] = listValves
            else:
                # add new
                settingsAdvancePumpTMP['PumpNeedValvesOff'].append(listValves)

        mutexAdvPump.acquire()
        settingsAdvancePump = copy.deepcopy(settingsAdvancePumpTMP)
        if len(settingsAdvancePump['PumpName']) > len(pumpsStateVect):
            increase = [False] * (len(settingsAdvancePump['PumpName']) - len(pumpsStateVect))
            pumpsStateVect.extend(increase)
        elif len(settingsAdvancePump['PumpName']) < len(pumpsStateVect):
            pumpsStateVect = pumpsStateVect[:len(settingsAdvancePump['PumpName'])]
        mutexAdvPump.release()

        # save new configuration to file
        with open(u"./data/advance_control.json", u"w") as f:  # write the settings to file
            json.dump(settingsAdvancePumpTMP, f, indent=4)

        web.seeother(u"/advance-pump-set")  # Return to definition pannel

class delete_pump(ProtectedPage):
    """
    Delete pump
    """

    def GET(self):

        # TODO delete pump

        web.seeother(u"/advance-pump-set")  # Return to definition pannel
