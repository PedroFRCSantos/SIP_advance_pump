
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
    from db_logger_generic_table import create_generic_table, change_table_name, add_date_generic_table, change_last_register
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
    u"/advance-pump-is-online", u"plugins.advance_pump.pump_is_online",
    u"/advance-pump-switch-state", u"plugins.advance_pump.pump_is_on",
    u"/advance-pump-switch-manual", u"plugins.advance_pump.pump_change_manual_state"
    ])
# fmt: on

# Add this plugin to the PLUGINS menu ["Menu Name", "URL"], (Optional)
gv.plugin_menu.append([_(u"Advance Pump"), u"/advance-pump-home"])

settingsAdvancePump = {'PumpName': [], 'PumpDeviceType': [], 'PumpIP': [], 'PumpNeedValves': [], 'PumpNeedValvesOn': [], 'PumpNeedValvesOff': [], 'PumpKeepState': []}
advancePumpManualMode = {}
mutexAdvPump = Lock()

def requestHTTP(commandURL):
    resposeIsOk = -1
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

    return resposeIsOk, response

def pumpIsOnLine(deviceType : str, pumpIP : str):
    resposeIsOk = -1
    isTurnOn = False

    if deviceType == 'shelly1':
        commandURL = u"http://" + pumpIP + u"/status"
        response = None

        resposeIsOk, response = requestHTTP(commandURL)

        if resposeIsOk == 0:
            isTurnOn = bool(response['relays'][0]['ison'])
    else:
        pass
        # TODO: another supported device

    return resposeIsOk, isTurnOn

def pupmpAction(deviceType : str, pumpIP : str, setState : bool):
    resposeIsOk = -1

    if deviceType == 'shelly1':
        if setState:
            commandURL = u"http://" + pumpIP + u"/relay/0?turn=on"
        else:
            commandURL = u"http://" + pumpIP + u"/relay/0?turn=off"
        response = None

        resposeIsOk, response = requestHTTP(commandURL)
    else:
        pass
        # TODO: another supported device

    return resposeIsOk

def runTreadPump():
    global settingsAdvancePump, mutexAdvPump, pumpsStateVect, lasTimeOnLine, switchPumpStatus, advancePumpManualMode

    mutexAdvPump.acquire()
    lastPupState = copy.deepcopy(pumpsStateVect)
    lastAdvPumpManualMode = copy.deepcopy(advancePumpManualMode)
    mutexAdvPump.release()

    lastTime = datetime.now()

    # Check if to save pumps logs in data-base
    mutexAdvPump.acquire()
    localSettings = copy.deepcopy(settingsAdvancePump)
    mutexAdvPump.release()
    if withDBLogger and localSettings['PumpDBLog']:
        dbDefinitions = db_logger_read_definitions()
    else:
        dbDefinitions = {}

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
            for newPump in range(len(pumpsStateVect)):
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

        # check pupms in manual mode
        for pumpIdManual in advancePumpManualMode:
            # pump force to turn off
            if not advancePumpManualMode[pumpIdManual] and pumpIdManual in listPups2TurnOn:
                listPups2TurnOn.remove(pumpIdManual)
            if not advancePumpManualMode[pumpIdManual] and pumpIdManual not in listPups2TurnOff and (pumpIdManual not in lastAdvPumpManualMode or lastAdvPumpManualMode[pumpIdManual]):
                listPups2TurnOff.append(pumpIdManual)

            # pump force to turn on
            if advancePumpManualMode[pumpIdManual] and pumpIdManual not in listPups2TurnOn and (pumpIdManual not in lastAdvPumpManualMode or not lastAdvPumpManualMode[pumpIdManual]):
                listPups2TurnOn.append(pumpIdManual)
            if advancePumpManualMode[pumpIdManual] and pumpIdManual in listPups2TurnOff:
                listPups2TurnOff.remove(pumpIdManual)

            # remove keep state if in manual mode
            if pumpIdManual in listPups2KeepOn:
                listPups2KeepOn.remove(pumpIdManual)
            if pumpIdManual in listPups2KeepOff:
                listPups2KeepOff.remove(pumpIdManual)

        # save last pupms stats, to check changes
        lastPupState = copy.deepcopy(pumpsStateVect)
        mutexAdvPump.release()

        # send signal to station that change to ON
        for pupmpIdOn in listPups2TurnOn:
            if pupmpIdOn < len(localSettings):
                pupmpAction(localSettings['PumpDeviceType'][pupmpIdOn], localSettings['PumpIP'][pupmpIdOn], True)
                # save to DB turn on register
                listElements = {"AdvancePumpDateBegin": "datetime", "AdvancePumpDateEnd": "datetime"}
                create_generic_table("advance_pump_" + localSettings['PumpName'][pupmpIdOn].strip(), listElements, dbDefinitions)
                turnOnDateTime = datetime.now()
                listData = [turnOnDateTime.strftime("%Y-%m-%d %H:%M:%S"), turnOnDateTime.strftime("%Y-%m-%d %H:%M:%S")]
                add_date_generic_table("advance_pump_" + localSettings['PumpName'][pupmpIdOn].strip(), listData, dbDefinitions)

        # send signal to station that change to OFF
        for pupmpIdOff in listPups2TurnOff:
            if pupmpIdOff < len(localSettings):
                pupmpAction(localSettings['PumpDeviceType'][pupmpIdOff], localSettings['PumpIP'][pupmpIdOff], False)
                # save to DB turn off register
                listElements = {"AdvancePumpDateBegin": "datetime", "AdvancePumpDateEnd": "datetime"}
                create_generic_table("advance_pump_" + localSettings['PumpName'][pupmpIdOn].strip(), listElements, dbDefinitions)
                turnOffDateTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                change_last_register("advance_pump_" + localSettings['PumpName'][pupmpIdOn].strip(), 2, turnOffDateTime, dbDefinitions)

        # every 30 seconds force state if needed and check if valves are only
        nowTime = datetime.now()
        diffTime = nowTime - lastTime
        secondsInt = int(diffTime.seconds)
        if secondsInt > 30 or len(listPups2TurnOn) > 0 or len(listPups2TurnOff) > 0:
            lastTime = nowTime

            # send signal to all pumps to keep on
            for currPumpKeepOnId in listPups2KeepOn:
                if localSettings['PumpKeepState'][currPumpKeepOnId]:
                    pupmpAction(localSettings['PumpDeviceType'][currPumpKeepOnId], localSettings['PumpIP'][currPumpKeepOnId], True)

            # send signal to all pumps to keep off
            for currPumpKeepOffId in listPups2KeepOff:
                if localSettings['PumpKeepState'][currPumpKeepOffId]:
                    pupmpAction(localSettings['PumpDeviceType'][currPumpKeepOffId], localSettings['PumpIP'][currPumpKeepOffId], False)

            # check if all pupms are on-line and states
            mutexAdvPump.acquire()
            localOnlineState = copy.deepcopy(lasTimeOnLine)
            localValveState = copy.deepcopy(switchPumpStatus)
            mutexAdvPump.release()

            for pumpsCheck in range(len(localSettings['PumpName'])):
                resposeIsOk, isTurnOn = pumpIsOnLine(localSettings['PumpDeviceType'][pumpsCheck], localSettings['PumpIP'][pumpsCheck])
                if resposeIsOk == 0:
                    localOnlineState[pumpsCheck] = datetime.now()

                    localValveState[pumpsCheck] = isTurnOn
                else:
                    localValveState[pumpsCheck] = False

                    # if became off-line save to logs in DB
                    if True:
                        pass

            mutexAdvPump.acquire()
            lasTimeOnLine = copy.deepcopy(localOnlineState)
            switchPumpStatus = copy.deepcopy(localValveState)
            lastAdvPumpManualMode = copy.deepcopy(advancePumpManualMode)
            mutexAdvPump.release()

# Read in the commands for this plugin from it's JSON file
def load_advance_pump():
    global settingsAdvancePump, mutexAdvPump, pumpsStateVect, lasTimeOnLine, switchPumpStatus

    mutexAdvPump.acquire()

    try:
        with open(u"./data/advance_pump.json", u"r") as f:  # Read settings from json file if it exists
            settingsAdvancePump = json.load(f)
    except IOError:  # If file does not exist return empty value
        # write default values to files
        with open(u"./data/advance_pump.json", u"w") as f:  # Edit: change name of json file
                json.dump(settingsAdvancePump, f)  # save to file

    pumpsStateVect = [False] * len(settingsAdvancePump['PumpName'])
    lasTimeOnLine = [datetime.now()] * len(settingsAdvancePump['PumpName'])
    switchPumpStatus = [False] * len(settingsAdvancePump['PumpName'])

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
        global settingsAdvancePump, mutexAdvPump, advancePumpManualMode

        mutexAdvPump.acquire()
        settings = copy.deepcopy(settingsAdvancePump)
        advancePumpManualModeLocal = copy.deepcopy(advancePumpManualMode)
        mutexAdvPump.release()

        return template_render.advance_pump_home(settings, advancePumpManualModeLocal)  # open settings page

class settings(ProtectedPage):
    """
    Load an html page for entering plugin settings.
    """

    def GET(self):
        global mutexAdvPump, settingsAdvancePump, withDBLogger

        mutexAdvPump.acquire()
        settingsAdvancePumpLocal = copy.deepcopy(settingsAdvancePump)
        mutexAdvPump.release()

        qdict = web.input()

        addPump = 0
        if "AddPumps" in qdict:
            addPump = int(qdict["AddPumps"])

        return template_render.advance_pump(settingsAdvancePumpLocal, addPump, withDBLogger)  # open settings page

class save_settings(ProtectedPage):
    """
    Load an html page for entering plugin settings.
    """

    def GET(self):
        global settingsAdvancePump, mutexAdvPump, pumpsStateVect, lasTimeOnLine, switchPumpStatus

        mutexAdvPump.acquire()
        settingsAdvancePumpTMP = copy.deepcopy(settingsAdvancePump)
        mutexAdvPump.release()

        qdict = web.input()

        initialSize = len(settingsAdvancePumpTMP['PumpName'])
        addNew = 0
        if "pumpName" + str(initialSize) in qdict:
            addNew = 1

        # Check if to save pumps logs in data-base
        settingsAdvancePumpTMP['PumpDBLog'] = "pumpDBLog" in qdict
        if withDBLogger and settingsAdvancePumpTMP['PumpDBLog']:
            dbDefinitions = db_logger_read_definitions()
        else:
            dbDefinitions = {}

        # Get name of pupms
        listElements = {"AdvancePumpDateBegin": "datetime", "AdvancePumpDateEnd": "datetime"}
        listElementsEvents = {"AdvancePumpLogsDate": "datetime", "AdvancePumpLogsData": "text"}

        for pumpId in range(initialSize + addNew):
            if "pumpName" + str(pumpId) in qdict:
                if pumpId < initialSize:
                    oldName = settingsAdvancePumpTMP['PumpName'][pumpId].strip()
                    settingsAdvancePumpTMP['PumpName'][pumpId] = qdict["pumpName" + str(pumpId)]

                    if withDBLogger and settingsAdvancePumpTMP['PumpDBLog']:                        
                        if "pumpIsTheSame" + str(pumpId) in qdict:
                            # rename table
                            create_generic_table("advance_pump_" + oldName, listElements, dbDefinitions)
                            create_generic_table("advance_pump_logs_" + oldName, listElementsEvents, dbDefinitions)
                            if "advance_pump_" + oldName != "advance_pump_" + settingsAdvancePumpTMP['PumpName'][pumpId].strip():
                                change_table_name("advance_pump_" + oldName, "advance_pump_" + settingsAdvancePumpTMP['PumpName'][pumpId].strip(), dbDefinitions)
                                change_table_name("advance_pump_logs_" + oldName, "advance_pump_logs_" + settingsAdvancePumpTMP['PumpName'][pumpId].strip(), dbDefinitions)
                        else:
                            create_generic_table("advance_pump_" + settingsAdvancePumpTMP['PumpName'][pumpId].strip(), listElements, dbDefinitions)
                            create_generic_table("advance_pump_logs_" + settingsAdvancePumpTMP['PumpName'][pumpId].strip(), listElementsEvents, dbDefinitions)
                else:
                    settingsAdvancePumpTMP['PumpName'].append(qdict["pumpName" + str(pumpId)])

                    create_generic_table("advance_pump_" + qdict["pumpName" + str(pumpId)], listElements, dbDefinitions)
                    create_generic_table("advance_pump_logs_" + qdict["pumpName" + str(pumpId)], listElementsEvents, dbDefinitions)

        # pump device type
        for pumpId in range(initialSize + addNew):
            if "deviceType" + str(pumpId) in qdict:
                if pumpId < initialSize:
                    settingsAdvancePumpTMP['PumpDeviceType'][pumpId] = qdict["deviceType" + str(pumpId)]
                else:
                    settingsAdvancePumpTMP['PumpDeviceType'].append(qdict["deviceType" + str(pumpId)])

        # Get pump IP
        for pumpId in range(initialSize + addNew):
            if "deviceIP" + str(pumpId) in qdict:
                if pumpId < initialSize:
                    settingsAdvancePumpTMP['PumpIP'][pumpId] = qdict["deviceIP" + str(pumpId)]
                else:
                    settingsAdvancePumpTMP['PumpIP'].append(qdict["deviceIP" + str(pumpId)])

        # check if pupm to keep state
        for pumpId in range(initialSize + addNew):
            if pumpId < initialSize:
                settingsAdvancePumpTMP['PumpKeepState'][pumpId] = "deviceForceState" + str(pumpId) in qdict
            else:
                settingsAdvancePumpTMP['PumpKeepState'].append("deviceForceState" + str(pumpId) in qdict)


        # Get list of valves need of working of pump
        for pumpId in range(initialSize + addNew):
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
        for pumpId in range(initialSize + addNew):
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
        for pumpId in range(initialSize + addNew):
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

            increase = [datetime.now()] * (len(settingsAdvancePump['PumpName']) - len(pumpsStateVect))
            lasTimeOnLine.extend(increase)

            switchPumpStatus = [False] * (len(settingsAdvancePump['PumpName']) - len(pumpsStateVect))
            switchPumpStatus.extend(switchPumpStatus)
        elif len(settingsAdvancePump['PumpName']) < len(pumpsStateVect):
            pumpsStateVect = pumpsStateVect[:len(settingsAdvancePump['PumpName'])]
            lasTimeOnLine = lasTimeOnLine[:len(settingsAdvancePump['PumpName'])]
            switchPumpStatus = switchPumpStatus[:len(settingsAdvancePump['PumpName'])]
        mutexAdvPump.release()

        # save new configuration to file
        with open(u"./data/advance_pump.json", u"w") as f:  # write the settings to file
            json.dump(settingsAdvancePumpTMP, f, indent=4)

        web.seeother(u"/advance-pump-set")  # Return to definition pannel

class delete_pump(ProtectedPage):
    """
    Delete pump
    """

    def GET(self):
        global settingsAdvancePump, mutexAdvPump, pumpsStateVect, lasTimeOnLine, switchPumpStatus

        qdict = web.input()

        pump2Delete = 0
        if "PumpId" in qdict:
            pump2Delete = int(qdict["PumpId"])

        mutexAdvPump.acquire()
        if pump2Delete < len(pumpsStateVect):
            del pumpsStateVect[pump2Delete]
            del lasTimeOnLine[pump2Delete]
            del switchPumpStatus[pump2Delete]

            del settingsAdvancePump['PumpName'][pump2Delete]
            del settingsAdvancePump['PumpDeviceType'][pump2Delete]
            del settingsAdvancePump['PumpIP'][pump2Delete]
            del settingsAdvancePump['PumpNeedValves'][pump2Delete]
            del settingsAdvancePump['PumpNeedValvesOn'][pump2Delete]
            del settingsAdvancePump['PumpNeedValvesOff'][pump2Delete]
            del settingsAdvancePump['PumpKeepState'][pump2Delete]

            settingsAdvancePumpTMP = copy.deepcopy(settingsAdvancePump)
        mutexAdvPump.release()

        # save new configuration to file
        with open(u"./data/advance_pump.json", u"w") as f:  # write the settings to file
            json.dump(settingsAdvancePumpTMP, f, indent=4)

        web.seeother(u"/advance-pump-set")  # Return to definition pannel

class pump_is_online(ProtectedPage):
    """
    Check if pump is online
    """

    def GET(self):
        global mutexAdvPump, lasTimeOnLine

        qdict = web.input()
        if "PumpId" in qdict:
            idxPump = int(qdict["PumpId"])
            currentDatime = datetime.now()
            mutexAdvPump.acquire()
            if idxPump >= 0 and idxPump < len(lasTimeOnLine):
                lastSeen = lasTimeOnLine[idxPump]
            else:
                lastSeen = datetime.now()
                return "<b style=\"color:gray;\">NONE</b>"
            mutexAdvPump.release()

            diffTime = currentDatime - lastSeen
            secondsInt = int(diffTime.seconds)
            if secondsInt > 45:
                return "<b style=\"color:red;\">OFFLINE</b>"
            else:
                return "<b style=\"color:green;\">ONLINE</b>"

        return "<b style=\"color:gray;\">NONE</b>"

class pump_is_on(ProtectedPage):
    """
    Check if pump is on
    """

    def GET(self):
        global mutexAdvPump, lasTimeOnLine, switchPumpStatus

        qdict = web.input()
        if "PumpId" in qdict:
            idxPump = int(qdict["PumpId"])
            mutexAdvPump.acquire()
            if idxPump >= 0 and idxPump < len(lasTimeOnLine):
                if switchPumpStatus[idxPump]:
                    mutexAdvPump.release()
                    return "<b style=\"color:green;\">ON</b>"
                else:
                    mutexAdvPump.release()
                    return "<b style=\"color:red;\">OFF</b>"

            mutexAdvPump.release()

        return "<b style=\"color:gray;\">NONE</b>"

class pump_change_manual_state(ProtectedPage):
    """
    change manual mode pumps states
    """

    def GET(self):
        global mutexAdvPump, lasTimeOnLine, switchPumpStatus, settingsAdvancePump

        qdict = web.input()
        if "PumpId" in qdict:
            idxPump = int(qdict["PumpId"])
            if "ChangeStateState" in qdict:
                mutexAdvPump.acquire()
                if qdict["ChangeStateState"] == 'auto' and idxPump in advancePumpManualMode:
                    del advancePumpManualMode[idxPump]
                elif qdict["ChangeStateState"] == 'on':
                    advancePumpManualMode[idxPump] = True
                elif qdict["ChangeStateState"] == 'off':
                    advancePumpManualMode[idxPump] = False

                pumpType = settingsAdvancePump['PumpDeviceType'][idxPump]
                pumpIP = settingsAdvancePump['PumpIP'][idxPump]
                mutexAdvPump.release()

                if qdict["ChangeStateState"] == 'on':
                    # send on signal
                    pupmpAction(pumpType, pumpIP, True)
                elif qdict["ChangeStateState"] == 'off':
                    # send off signal
                    pupmpAction(pumpType, pumpIP, False)

                if qdict["ChangeStateState"] == 'on' or qdict["ChangeStateState"] == 'off':
                    # check status
                    resposeIsOk, isTurnOn = pumpIsOnLine(pumpType, pumpIP)

                    mutexAdvPump.acquire()
                    if resposeIsOk == 0:
                        lasTimeOnLine[idxPump] = datetime.now()

                        switchPumpStatus[idxPump] = isTurnOn
                    else:
                        switchPumpStatus[idxPump] = False
                    mutexAdvPump.release()

                # return next state
                if qdict["ChangeStateState"] == 'on':
                    return '<button class="submit" onclick="sendPumpSwitchChange(\'off\', '+ str(idxPump) +')"><b>Turn Switch Off</b></button>'
                elif qdict["ChangeStateState"] == 'off':
                    return '<button class="submit" onclick="sendPumpSwitchChange(\'auto\', '+ str(idxPump) +')"><b>Turn Switch Auto</b></button>'
                elif qdict["ChangeStateState"] == 'auto':
                    return '<button class="submit" onclick="sendPumpSwitchChange(\'on\', '+ str(idxPump) +')"><b>Turn Switch On</b></button>'

        return ""
