#!/usr/bin/env python
# vim: ts=2 sw=2 et

# import normal packages
import platform 
import logging
import sys
import os
import sys
if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject
import sys
import time
import requests # for http GET
import configparser # for config/ini file
 
# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService


class DbusShelly3emService:
  def __init__(self, productname='Shelly 3EM', connection='Shelly 3EM HTTP JSON service'):
    self.config = self._getConfig()
    self.URL = self._getShellyStatusUrl()
    deviceinstance = int(self.config['DEFAULT']['DeviceInstance'])
    customname = self.config['DEFAULT']['CustomName']
    role = self.config['DEFAULT']['Role']

    allowed_roles = ['pvinverter','grid']
    if role in allowed_roles:
        servicename = 'com.victronenergy.' + role
    else:
        logging.error("Configured Role: %s is not in the allowed list")
        exit()

    if role == 'pvinverter':
        productid = 0xA144
    else:
        productid = 45069

    self.phaseIndex = [0, 1, 2]
    try:
        remapL1 = int(self.config['ONPREMISE']['L1Position'])
    except KeyError:
        remapL1 = 1
    else:
        self.phaseIndex[0] = remapL1-1
        self.phaseIndex[remapL1-1] = 0

    self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
 
    logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))
 
    # Create the management objects, as specified in the ccgx dbus-api document
    self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
    self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self._dbusservice.add_path('/Mgmt/Connection', connection)
 
    # Create the mandatory objects
    self._dbusservice.add_path('/DeviceInstance', deviceinstance)
    self._dbusservice.add_path('/ProductId', productid)
    self._dbusservice.add_path('/DeviceType', 345) # found on https://www.sascha-curth.de/projekte/005_Color_Control_GX.html#experiment - should be an ET340 Engerie Meter
    self._dbusservice.add_path('/ProductName', productname)
    self._dbusservice.add_path('/CustomName', customname)
    self._dbusservice.add_path('/Latency', None)
    self._dbusservice.add_path('/FirmwareVersion', 0.3)
    self._dbusservice.add_path('/HardwareVersion', 0)
    self._dbusservice.add_path('/Connected', 1)
    self._dbusservice.add_path('/Role', role)
    self._dbusservice.add_path('/Position', self._getShellyPosition()) # normaly only needed for pvinverter
    self._dbusservice.add_path('/Serial', self._getShellySerial())
    self._dbusservice.add_path('/UpdateIndex', 0)
 
    # add path values to dbus
    #formatting 
    _kwh = lambda p, v: (str(round(v, 2)) + ' kWh')
    _a = lambda p, v: (str(round(v, 1)) + ' A')
    _w = lambda p, v: (str(round(v, 1)) + ' W')
    _v = lambda p, v: (str(round(v, 1)) + ' V')   
   
    #start our main-service
    paths={
          '/Ac/Energy/Forward': {'initial': 0, 'textformat': _kwh}, # energy bought from the grid
          '/Ac/Energy/Reverse': {'initial': 0, 'textformat': _kwh}, # energy sold to the grid
          '/Ac/Power': {'initial': 0, 'textformat': _w},
          
          '/Ac/Current': {'initial': 0, 'textformat': _a},
          '/Ac/Voltage': {'initial': 0, 'textformat': _v},
          
          '/Ac/L1/Voltage': {'initial': 0, 'textformat': _v},
          '/Ac/L2/Voltage': {'initial': 0, 'textformat': _v},
          '/Ac/L3/Voltage': {'initial': 0, 'textformat': _v},
          '/Ac/L1/Current': {'initial': 0, 'textformat': _a},
          '/Ac/L2/Current': {'initial': 0, 'textformat': _a},
          '/Ac/L3/Current': {'initial': 0, 'textformat': _a},
          '/Ac/L1/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L2/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L3/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L1/Energy/Forward': {'initial': 0, 'textformat': _kwh},
          '/Ac/L2/Energy/Forward': {'initial': 0, 'textformat': _kwh},
          '/Ac/L3/Energy/Forward': {'initial': 0, 'textformat': _kwh},
          '/Ac/L1/Energy/Reverse': {'initial': 0, 'textformat': _kwh},
          '/Ac/L2/Energy/Reverse': {'initial': 0, 'textformat': _kwh},
          '/Ac/L3/Energy/Reverse': {'initial': 0, 'textformat': _kwh},
    }
    for path, settings in paths.items():
      self._dbusservice.add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True)
 
    # last update
    self._lastUpdate = time.time() - 0.5
 
    # add _update function 'timer'
    gobject.timeout_add(500, self._update) # pause 500ms before the next request
    
    # add _signOfLife 'timer' to get feedback in log every 5minutes
    gobject.timeout_add(self._getSignOfLifeInterval()*60*1000, self._signOfLife)
 
  def _getShellySerial(self):
    meter_data = self._getShellyData()  
    
    if not meter_data['mac']:
        raise ValueError("Response does not contain 'mac' attribute")
    
    serial = meter_data['mac']
    return serial
 
 
  def _getConfig(self):
    config = configparser.ConfigParser()
    config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
    return config;
 
 
  def _getSignOfLifeInterval(self):
    value = self.config['DEFAULT']['SignOfLifeLog']
    
    if not value: 
        value = 0
    
    return int(value)
 
 
  def _getShellyPosition(self):
    value = self.config['DEFAULT']['Position']
    
    if not value: 
        value = 0
    
    return int(value)
 
 
  def _getShellyStatusUrl(self):
    accessType = self.config['DEFAULT']['AccessType']
    
    if accessType == 'OnPremise': 
        URL = "http://%s:%s@%s/status" % (self.config['ONPREMISE']['Username'], self.config['ONPREMISE']['Password'], self.config['ONPREMISE']['Host'])
        URL = URL.replace(":@", "")
    else:
        raise ValueError("AccessType %s is not supported" % (self.config['DEFAULT']['AccessType']))
    
    return URL
    
 
  def _getShellyData(self):
    # URL = self._getShellyStatusUrl()
    meter_r = requests.get(url = self.URL, timeout=5)
    
    # check for response
    if not meter_r:
        raise ConnectionError("No response from Shelly 3EM - %s" % (self.URL))
    
    meter_data = meter_r.json()     
    
    # check for Json
    if not meter_data:
        raise ValueError("Converting response to JSON failed")
    
    
    return meter_data
 
 
  def _signOfLife(self):
    logging.info("--- Start: sign of life ---")
    logging.info("Last _update() call: %s" % (self._lastUpdate))
    logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
    logging.info("--- End: sign of life ---")
    return True
 
  def _update(self):   
    try:
      #get data from Shelly 3em
      meter_data = self._getShellyData()

      # xxx if l1position = 1 -> index 0 is stored in index 0
      # xxx if l1position = 2 -> index 1 is stored in index 0

      l1data = meter_data['emeters'][self.phaseIndex[0]]
      l2data = meter_data['emeters'][self.phaseIndex[1]]
      l3data = meter_data['emeters'][self.phaseIndex[2]]

      #send data to DBus
      acpower = meter_data['total_power']
      self._dbusservice['/Ac/Power'] = acpower
      self._dbusservice['/Ac/L1/Voltage'] = l1data['voltage']
      self._dbusservice['/Ac/L2/Voltage'] = l2data['voltage']
      self._dbusservice['/Ac/L3/Voltage'] = l3data['voltage']
      self._dbusservice['/Ac/L1/Current'] = l1data['current']
      self._dbusservice['/Ac/L2/Current'] = l2data['current']
      self._dbusservice['/Ac/L3/Current'] = l3data['current']
      self._dbusservice['/Ac/L1/Power'] = l1data['power']
      self._dbusservice['/Ac/L2/Power'] = l2data['power']
      self._dbusservice['/Ac/L3/Power'] = l3data['power']
      self._dbusservice['/Ac/L1/Energy/Forward'] = (l1data['total']/1000)
      self._dbusservice['/Ac/L2/Energy/Forward'] = (l2data['total']/1000)
      self._dbusservice['/Ac/L3/Energy/Forward'] = (l3data['total']/1000)
      self._dbusservice['/Ac/L1/Energy/Reverse'] = (l1data['total_returned']/1000) 
      self._dbusservice['/Ac/L2/Energy/Reverse'] = (l2data['total_returned']/1000) 
      self._dbusservice['/Ac/L3/Energy/Reverse'] = (l3data['total_returned']/1000) 
      
      # Old version
      #self._dbusservice['/Ac/Energy/Forward'] = self._dbusservice['/Ac/L1/Energy/Forward'] + self._dbusservice['/Ac/L2/Energy/Forward'] + self._dbusservice['/Ac/L3/Energy/Forward']
      #self._dbusservice['/Ac/Energy/Reverse'] = self._dbusservice['/Ac/L1/Energy/Reverse'] + self._dbusservice['/Ac/L2/Energy/Reverse'] + self._dbusservice['/Ac/L3/Energy/Reverse'] 
     
      t = time.time()
      dt = t - self._lastUpdate
      #update lastupdate vars
      self._lastUpdate = t

      # New Version - from xris99
      #Calc = 60min * 60 sec / dt (refresh interval of 500ms) * 1000
      f = 3600000 / dt

      forward_e = self._dbusservice['/Ac/Energy/Forward']
      reverse_e = self._dbusservice['/Ac/Energy/Reverse']

      if (acpower > 0):
           forward_e += (acpower / f)            
           self._dbusservice['/Ac/Energy/Forward'] = forward_e
      elif (acpower < 0):
           reverse_e -= (acpower / f)            
           self._dbusservice['/Ac/Energy/Reverse'] = reverse_e

      
      #logging
      logging.debug("House Consumption (/Ac/Power): %s" % acpower)
      logging.debug("House Forward (/Ac/Energy/Forward): %s" % forward_e)
      logging.debug("House Reverse (/Ac/Energy/Revers): %s" % reverse_e)
      logging.debug("---");
      
      # increment UpdateIndex - to show that new data is available an wrap
      self._dbusservice['/UpdateIndex'] = (self._dbusservice['/UpdateIndex'] + 1 ) % 256

    except (ValueError, requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionError) as e:
       logging.critical('Error getting data from Shelly - check network or Shelly status. Setting power values to 0. Details: %s', e, exc_info=e)       
       self._dbusservice['/Ac/L1/Power'] = 0                                       
       self._dbusservice['/Ac/L2/Power'] = 0                                       
       self._dbusservice['/Ac/L3/Power'] = 0
       self._dbusservice['/Ac/Power'] = 0
       self._dbusservice['/UpdateIndex'] = (self._dbusservice['/UpdateIndex'] + 1 ) % 256        
    except Exception as e:
       logging.critical('Error at %s', '_update', exc_info=e)
       
    # return true, otherwise add_timeout will be removed from GObject - see docs http://library.isr.ist.utl.pt/docs/pygtk2reference/gobject-functions.html#function-gobject--timeout-add
    return True
 
def getLogLevel():
  config = configparser.ConfigParser()
  config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
  logLevelString = config['DEFAULT']['LogLevel']
  
  if logLevelString:
    level = logging.getLevelName(logLevelString)
  else:
    level = logging.INFO
    
  return level


def main():
  #configure logging
  logging.basicConfig(      format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=getLogLevel()
                      )
 
  try:
      logging.info("Start");
  
      from dbus.mainloop.glib import DBusGMainLoop
      # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
      DBusGMainLoop(set_as_default=True)
     
      #start our main-service
      pvac_output = DbusShelly3emService()
     
      logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
      mainloop = gobject.MainLoop()
      mainloop.run()            
  except (ValueError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
    logging.critical('Error in main type %s', str(e))
  except Exception as e:
    logging.critical('Error at %s', 'main', exc_info=e)
if __name__ == "__main__":
  main()
