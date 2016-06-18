import os
from PyQt5.QtCore import QObject, QCoreApplication

import UI
from E5Gui.E5Application import e5App
import Preferences
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from threading import Thread
from PycomDevice import pyboard
import time

# Start-Of-Header
name = "Pycom Device"
author = "Pycom"
autoactivate = True
deactivateable = False
version = "1.0.0"
className = "PluginPycomDevice"
packageName = "PluginPycomDevice"
shortDescription = "Communicate with Pycom devices"
longDescription = "Allow other plugins to connect to Pycom devices"

pyqtApi = 2
python2Compatible = True

PycomDevicePluginObject = None

def getConfigData():
    """
    Module function returning data as required by the configuration dialog.

    @return dictionary with key "PycomDevice" containing the relevant
        data
    """
    path = os.path.dirname(os.path.realpath(__file__))
    return {
        "PycomDevice":
        [QCoreApplication.translate("PycomDevicePlugin", "Pycom Device"),
        path + "/PycomDevice/img/chip.png", createConfigurationPage,
        None, None]
    }

def createConfigurationPage(configDlg):
    """
    Module function to create the configuration page.

    @param configDlg reference to the configuration dialog (QDialog)
    @return reference to the configuration page
    """
    global PycomDevicePluginObject
    from PycomDevice.ConfigurationPage.PycomDevicePage import PycomDevicePage
    return PycomDevicePage(PycomDevicePluginObject)

class PluginPycomDevice(QObject):
    def __init__(self,  ui):
        global PycomDevicePluginObject

        super(PluginPycomDevice, self).__init__(ui)
        PycomDevicePluginObject = self

        self.__ui = ui
        self.__oldShowEvent = self.__ui.showEvent
        self.__ui.showEvent = self.__onWindowLoad
        self.__oldCloseEvent = self.__ui.closeEvent
        self.__ui.closeEvent = self.__onWindowUnload

        self.__windowLoaded = False
        self.__path = os.path.dirname(os.path.realpath(__file__))
        UI.PixmapCache.addSearchPath(self.__path + "/PycomDevice/img")

    def activate(self):
        """
        Public method to activate this plugin.
        
        @return tuple of None and activation status (boolean)
        """
        self.__active = True
        if self.__windowLoaded == True:
            self.__initializeShell()
        return None, True

    def deactivate(self):
        """
        Public method to deactivate this plugin.
        """
        self.__pds.disconnect()

    def __onWindowLoad(self, event):
        # I must run only once
        self.__ui.showEvent = self.__oldShowEvent
        self.__ui.showEvent(event)

        if self.__active == True:
            self.__initializeShell()
        self.__windowLoaded = True

    def __onWindowUnload(self, event):
        self.__ui.closeEvent = self.__oldCloseEvent
        self.__pds.disconnect()
        self.__ui.closeEvent(event)

    def __initializeShell(self):
        self.__pds = PycomDeviceServer()
        self.loadSettings()
        self.__pds.connect()

    def loadSettings(self):
        self.__pds.setConnectionParameters(
            self.getPreferences("address"),
            self.getPreferences("username"),
            self.getPreferences("password")
            )

    def getPreferences(self, name, default=None):
        return Preferences.Prefs.settings.value("PycomDevice/" + name, default)

    def setPreferences(self, name, value):
        Preferences.Prefs.settings.setValue("PycomDevice/" + name, value)

    def preferencesChanged(self):
        self.loadSettings()
        self.__pds.restart()

class PycomDeviceServer(QObject):
    clientOutput = pyqtSignal(str)
    statusChanged = pyqtSignal(str)
    channel = None
    __rx_thread = None
    __device = None
    __user = None
    __password = None

    def __init__(self):
        super(PycomDeviceServer, self).__init__()
        # A single set of signals is desired for all the instances of this Class

        # PyQt imposes the following limitation (in the documentation):
        #   "New signals should only be defined in sub-classes of QObject. 
        #   They must be part of the class definition and cannot be dynamically
        #   added as class attributes after the class has been defined."

        # By behavior, PyQt creates unbounded signals, and they'll become bounded
        # when an actual object exists
        # On the first run, clientOutput and statusChanged will be unbounded, hence
        # they won't have the emit member. If that's the case, the bounded versions
        # of the first instance (the one created on plugin init) will be copied in
        # their place 

        if not getattr(PycomDeviceServer.clientOutput, 'emit', None):
            # assume first time the init runs, won't test for both
            PycomDeviceServer.clientOutput = self.clientOutput
            PycomDeviceServer.statusChanged = self.statusChanged

        pluginManager = e5App().getObject("PluginManager")
        pluginManager.activatePlugin("PluginPycomDevice")
        PycomDeviceServer.__shutdown = False

    def connect(self):
        try:
            if self.getStatus() == True:
                return True
        except:
            pass

        try:
            if PycomDeviceServer.__rx_thread:
                return True
        except:
            pass

        try:
            if not PycomDeviceServer.__device:
                return False
            PycomDeviceServer.__rx_thread = Thread(target=self.__recvBackground, args=())
            PycomDeviceServer.__rx_thread.start()
        except:
            return False

        return True

    def disconnect(self):
        try:
            PycomDeviceServer.__shutdown = True
            PycomDeviceServer.channel.close()
        except:
            pass

    def shutdown(self):
        PycomDeviceServer.__shutdown = True

    def setConnectionParameters(self, device, user, password):
        PycomDeviceServer.__device = device
        PycomDeviceServer.__user = user
        PycomDeviceServer.__password = password

    def isConfigured(self):
        # return False on empty or None
        return not not PycomDeviceServer.__device

    def getStatus(self):
        try:
            return PycomDeviceServer.channel.check_connection()
        except:
            return False

    def __recvBackground(self):
        PycomDeviceServer.__shutdown = False
        while PycomDeviceServer.__shutdown == False:
            try:
                PycomDeviceServer.statusChanged.emit("connecting")
                PycomDeviceServer.channel = pyboard.Pyboard(device=PycomDeviceServer.__device,
                    user=PycomDeviceServer.__user, password=PycomDeviceServer.__password, keep_alive=3)
                PycomDeviceServer.channel.reset()
                PycomDeviceServer.statusChanged.emit("connected")
                PycomDeviceServer.channel.recv(self.signalClientOutput)
                PycomDeviceServer.statusChanged.emit("disconnected")
            except pyboard.PyboardError as er:
                if str(er) == "Invalid credentials":
                    PycomDeviceServer.statusChanged.emit("invcredentials")
                    break
                elif str(er) == "\nInvalid address":
                    PycomDeviceServer.statusChanged.emit("invaddress")
                    break
                else:
                    PycomDeviceServer.statusChanged.emit("error")
            except Exception as e:
                PycomDeviceServer.statusChanged.emit("error")

            if self.__keepTrying == False or PycomDeviceServer.__shutdown == True:
                break
            else:
                PycomDeviceServer.statusChanged.emit("reattempt")
                for t in xrange(0, 15 * 4):
                    time.sleep(1.0 / 4)
                    if PycomDeviceServer.__shutdown == True:
                        break
        PycomDeviceServer.__rx_thread = None


    def signalClientOutput(self, text):
        self.clientOutput.emit(text)

    def send(self, text):
        try:
            PycomDeviceServer.channel.send(text)
        except:
            pass

    def restart(self):
        try:
            if self.getStatus() == True:
                self.disconnect()
            if self.__keepTrying == True:
                time.sleep(0.25)
                self.connect()
        except:
            pass

    @pyqtSlot(bool)
    def tryConnecting(self, state):
        self.connect()
        self.__keepTrying = state