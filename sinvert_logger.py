#!/usr/bin/python3
# -*- coding: utf-8 -*-
import socket
import sys
import struct
import time
import pickle
import json
import pytz
import paho.mqtt.client as mqtt
import logging
from datetime import datetime
from collections import OrderedDict

logging.basicConfig(handlers=[logging.FileHandler(filename="./logfile.log", encoding='utf-8', mode='a+')], format="%(asctime)s %(name)s: %(levelname)s: %(message)s", datefmt="%F %A %T", level=logging.DEBUG)  # logging.INFO
#logging.basicConfig(filename="logfile.log", level=logging.DEBUG)

# logger = logging.getLogger()

minpythonversion = 0x3020000
if sys.hexversion < minpythonversion:
  # print('Python version ' + str(sys.version) + ' is too old, please use Python version 3.2 or newer!')
  logging.debug('Python version ' + str(sys.version) + ' is too old, please use Python version 3.2 or newer!')
  sys.exit()

# Version 4:
# -- Anbindung zu Volkszaehler ergaenzt
# -- Logging ergaenzt
# -- # -*- coding: utf-8 -*- und Ueberpruefung der Python version ergaenzt
# -- Standardmäßg wird jetzt Port 8080 fuer dieses prg verwendent, da auf port 80 der Dateizugriff auf den raspi manchmal nicht funktioniert(iptables müssen auch angepasst werden)
# -- Weiterleitung der Rohdaten vom WR jetzt ueber Schleife realisiert, 
# Programm zum Empfangen von Daten von Refusol/Sinvert/AdvancedEnergy Wechselrichter
# Getestet mit einem Sinvert PVM20 und einem RaspberryPi B

# Einstellungen im Wechselrichter:
# IP: Freie IP-Adresse im lokalen Netzwerk
# Netmask: 255.255.255.0
# Gateway: IP-Adresse des Rechners auf dessen dieses Prg laeuft(zb. Raspberry),

# Einstellungen am Rechner(zb. Raspberry)
# routing aktivieren
# sudo sh -c 'echo 1 > /proc/sys/net/ipv4/ip_forward'

# Pakete welche an die IP des Logportals gehen and die IP des Raspi umleiten und auf port 8080
# sudo iptables -t nat -A PREROUTING -d 88.79.234.30 -j DNAT --to-destination ip.des.rasp.berry --dport 8080
# hier: sudo iptables -t nat -A PREROUTING -d 195.27.237.106 -j DNAT --to-destination 192.168.0.212 --dport 80

# Pakete als absender die IP des Raspi eintragen
# sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

# Damit dies auch nach einem Neustart funktioniert auch in die crontab eintragen:
# sudo crontab -e
# @reboot sudo iptables -t nat -A PREROUTING -d 88.79.234.30 -j DNAT --to-destination ip.des.rasp.berry;sudo iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

# Im Program muss noch die IP des Raspberry geaendert werden,
# sowie die Pfade datalogpath, errlogpath, und loggingpath fuer den Speicherort der .csv files. Standard: "/home/pi/"
# Die Pfade(Ordner) muessen existieren, diese werden nicht automatisch erzeugt!

# Start des Programms via Kommandozeile
# sudo python3 /home/pi/RcvSendSinvertDaten_V4.py

# Damit nach Neustart automatisch gestartet wird in crontab eintragen:
# sudo crontab -e
# @reboot sudo python3 /home/pi/RcvSendSinvertDaten_V4.py

#Zeichenfolgen für Daten sind bei den verschiedenen Firmwareständen unterschiedlich:
#je nach Firmware mit "#" auskommentieren bzw. einkommentieren

#macaddr,endmacaddr = 'm="','"'#für neuere firmwares
tag_macaddr,tag_end_macaddr = '<m>','</m>'#für ältere firmwares

#firmware,endfirmware = 's="','"'#für neuere firmwares
tag_serialno,tag_end_serialno = '<s>','</s>'#für ältere firmwares

server_ip = '' #IP- des Raspi angeben, wenn keine IP angeben wird ==> Raspi lauscht auf allen zugewiesenen IP Adressen
server_port = 81 #Port auf dem das prg am raspi lauscht

# Server, an dessen die Daten 1:1 durchgereicht werden, Format: [('ipserver1',portserver1),('ipserver2',portserver2),usw...]
# Es k?nnen beliebig viele Server angegeben werden, diese werden in einer Schleife abgearbeitet
# Wenn an keine Server weitergereicht werden soll, dann: rawdataserver = []
# Hier: 5.45.98.160 -> greensynergy server
rawdataserver = [('5.45.98.160', 80)]

lsInverters = []

class Inverter:
  def __init__(self, serialno):  
    self.serialno = serialno
    self.logfile_data = ""
    self.logfile_data_name = "" # LBAN02261010321_data_YEAR_Month e.g. LBAN02261010321_data_2021_03
    self.logfile_error = ""
    self.logfile_error_name = "" # LBAN02261010321_error_YEAR_Month e.g. LBAN02261010321_error_2021_03
    self.setLogfiles("data")
    self.setLogfiles("error")

  def logDataMSG(self, msg):
    #print("Trying to log data... ")
    logging.debug("Trying to log data... ")

    actualFilename = self.composeActualFilename("data")
    logging.debug("actualFilename: " + str(actualFilename))

    if actualFilename == self.logfile_data_name:
      logging.debug("Actual filename ok...")
      self.logfile_data.write(msg + "\n")
    else:
      logging.info("Create new data logfile.")
      logging.info("actualFilename: " + str(actualFilename))
      self.setLogfiles("data")
      self.logfile_data.write(msg + "\n")
      
    self.logfile_data.flush()

    logging.debug("Logged in data logfile.")

  def logErrorMSG(self, msg):
    logging.debug("Trying to log error... ")

    actualFilename = self.composeActualFilename("error")
    if actualFilename == self.logfile_error_name:
      self.logfile_error.write(msg + "\n")
    else:
      logging.info("Create new error logfile.")
      logging.info("actualFilename: " + str(actualFilename))
      self.setLogfiles("error")
      self.logfile_error.write(msg + "\n")

    self.logfile_error.flush()

    logging.debug("Logged in error logfile.")

  # Compose the filename as it should be for the inverter and the current month and year
  def composeActualFilename(self, type):
    date = datetime.today()
    year = date.year
    month = date.month

    if type == "data":
      return self.serialno + "_data_" + str(year) + "_" + str(month) + ".txt"
    elif type == "error":
      return self.serialno + "_error_" + str(year) + "_" + str(month) + ".txt"
    else:
      return "Something went wrong"

  def setLogfiles(self, type):
    if type == "data":
      # close existing data log file
      if(hasattr(self.logfile_data, 'read')):
        try:
          logging.info("close existing data logfile...")
          self.logfile_data.close()
        except FileNotFoundError:
          logging.error("Data logfile not accessible")

      logging.debug("setup new data logfile")
      actualFilename = self.composeActualFilename("data")
      try:
        self.logfile_data = open(actualFilename, "a+") # if file exists, append data, if not create a new one
        self.logfile_data_name = actualFilename
        self.logfile_data.write("Data logfile (re-)opened...\n")
      except FileNotFoundError:
        logging.error("Data logfile not accessible")
    elif type == "error":
      # close existing error log file
      if(hasattr(self.logfile_error, 'read')):
        try:
          logging.info("close existing error logfile...")
          self.logfile_error.close()
        except FileNotFoundError:
          logging.error("Error logfile not accessible")

      logging.debug("setup new error logfile")
      actualFilename = self.composeActualFilename("error")
      try:
        self.logfile_error = open(actualFilename, "a+") # if file exists, append data, if not create a new one
        self.logfile_error_name = actualFilename
        self.logfile_error.write("Error logfile (re-)opened...\n")
      except FileNotFoundError:
        logging.error("Error logfile not accessible")
    else:
      logging.debug("Something went wrong (setLogfiles)")
      return "Something went wrong (setLogfiles)"


def byteorder():
  return sys.byteorder

def standard_encoding():
  return sys.getdefaultencoding()

def standardausgabe_encoding():
  return sys.stdout.encoding

def string2bytes(text):
  return bytes(text, "cp1252")

def bytes2string(bytes):
  return str(bytes, "cp1252")

def converthex2float(hexval):
  #print(hexval)
  try:
    return round(struct.unpack('>f', struct.pack('>I', int(float.fromhex(hexval))))[0],2)
  except BaseException as e:
    #print(str(e) + '\r\n')
    #logstring += str(e) + '\r\n' + 'Error while convert hex to float failed! hexvalue = ' + str(hexval) + '\r\n'
    logging.error(str(e) + '\r\n' + 'Error while convert hex to float failed! hexvalue = ' + str(hexval))
    return 0

def converthex2int(hexval):
  global logstring
  #print(hexval)
  try:
    return struct.unpack('>i', struct.pack('>I', int(float.fromhex(hexval))))[0]
  except BaseException as e:
    #print(str(e) + '\r\n')
    #logstring += str(e) + '\r\n' + 'Error while convert hex to int failed! hexvalue = ' + str(hexval) + '\r\n'
    logging.error(str(e) + '\r\n' + 'Error while convert hex to int failed! hexvalue = ' + str(hexval))
    return 0

def decodedata(rcv):#Daten decodieren
  dataset = {}
  operationaldata = {}

  index = tag_macaddr
  endindex = tag_end_macaddr
  if rcv.find(index) >= 0:
    dataset['mac_address'] = str(rcv[rcv.find(index)+3:rcv.find(endindex,rcv.find(index)+3)])
  else:
    dataset['mac_address'] = '0'

  index = tag_serialno
  endindex = tag_end_serialno
  if rcv.find(index) >= 0:
    dataset['serialno'] = str(rcv[rcv.find(index)+3:rcv.find(endindex,rcv.find(index)+3)])
  else:
    dataset['serialno'] = '0'

  index = 't="'
  if rcv.find(index) >= 0:
    timestamp = int((rcv[rcv.find(index)+3:rcv.find('"',rcv.find(index)+3)]))
    dataset['timestamp'] = timestamp
    dataset['datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp))
  else:
    dataset['timestamp'] = '0'
    dataset['datetime'] = '0'

  index = '" l="'
  if rcv.find(index) >= 0:
    dataset['loggerinterval'] = float(str((rcv[rcv.find(index)+5:rcv.find('"',rcv.find(index)+5)])))
  else:
    dataset['loggerinterval'] = 0

  index = 'i="1"'
  if rcv.find(index) >= 0:
    acleistung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['AC_power'] = float(acleistung)
  else:
    operationaldata['AC_power'] = 0

  index = 'i="2"'
  if rcv.find(index) >= 0:
    acspannung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['AC_voltage'] = float(acspannung)
  else:
    operationaldata['AC_voltage'] = 0

  index = 'i="3"'
  if rcv.find(index) >= 0:
    acstrom = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['AC_current'] = float(acstrom)
  else:
    operationaldata['AC_current'] = 0

  index = 'i="4"'
  if rcv.find(index) >= 0:
    acfrequenz = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['frequency'] = float(acfrequenz)
  else:
    operationaldata['frequency'] = 0

  index = 'i="5"'
  if rcv.find(index) >= 0:
    dcleistung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['DC_power'] = float(dcleistung)
  else:
    operationaldata['DC_power'] = 0

  index = 'i="6"'
  if rcv.find(index) >= 0:
    dcspannung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['DC_voltage'] = float(dcspannung)
  else:
    operationaldata['DC_voltage'] = 0

  index = 'i="7"'
  if rcv.find(index) >= 0:
    dcstrom = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['DC_current'] = float(dcstrom)
  else:
    operationaldata['DC_current'] = 0

  index = 'i="8"'
  if rcv.find(index) >= 0:
    temp1 = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['temperature_left'] = float(temp1)
  else:
    operationaldata['temperature_left'] = 0

  index = 'i="9"'
  if rcv.find(index) >= 0:
    temp2 = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['temperature_right'] = float(temp2)
  else:
    operationaldata['temperature_right'] = 0

  index = 'i="A"'
  if rcv.find(index) >= 0:
    einstrahlung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])) + ''
    operationaldata['irridation'] = float(einstrahlung)
  else:
    operationaldata['irridation'] = 0

  index = 'i="B"'
  if rcv.find(index) >= 0:
    modultemp = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])) + ''
    operationaldata['temperature_pvpanel'] = float(modultemp)
  else:
    operationaldata['temperature_pvpanel'] = 0

  index = 'i="C"'
  if rcv.find(index) >= 0:
    tagesertrag = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['daily_yield'] = float(tagesertrag)
  else:
    operationaldata['daily_yield'] = 0

  index = 'i="D"'
  if rcv.find(index) >= 0:
    status = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['status'] = int(float(status))
  else:
    operationaldata['status'] = 0

  index = 'i="E"'
  if rcv.find(index) >= 0:
    gesamtertrag = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['yield'] = float(gesamtertrag)
  else:
    operationaldata['yield'] = 0

  index = 'i="F"'
  if rcv.find(index) >= 0:
    betriebsstunden = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['operating_hours'] = float(betriebsstunden)
  else:
    operationaldata['operating_hours'] = 0

  index = 'i="10"'
  if rcv.find(index) >= 0:
    operationaldata['undefined1'] = float(str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10))
  else:
    operationaldata['undefined1'] = 0

  index = 'i="12"'
  if rcv.find(index) >= 0:
    leistungsbesch = str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10)
    operationaldata['undefined2'] = float(leistungsbesch)
  else:
    operationaldata['undefined2'] = 0

  index = 'i="11"'
  if rcv.find(index) >= 0:
    tagessonnenenergie = str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10)
    operationaldata['undefined3'] = float(tagessonnenenergie)
  else:
    operationaldata['undefined3'] = 0

  dataset['operationaldata'] = operationaldata
  logging.debug("JSON: " + json.dumps(dataset, sort_keys=True))
  # print("JSON: " + json.dumps(dataset, sort_keys=True)) # sort_keys=True
  return dataset

def decodeerr(rcv):#Störungen decodieren

  #xmlData=<re><m>502DF40048AF</m><s>LBAN02261010321</s><e><ts>1612105645</ts><code>a010c</code><state>2</state><short>0</short><long>2048</long><type>8</type><actstate>6</actstate></e></re>

  string = []
  errormsg = {}

  index = tag_macaddr
  endindex = tag_end_macaddr
  if rcv.find(index) >= 0:
    errormsg['mac_address'] = str(rcv[rcv.find(index)+3:rcv.find(endindex,rcv.find(index)+3)])
  else:
    errormsg['mac_address'] = "0"

  index = tag_serialno
  endindex = tag_end_serialno
  if rcv.find(index) >= 0:
    errormsg['serialno'] = str(rcv[rcv.find(index)+3:rcv.find(endindex,rcv.find(index)+3)])
  else:
    errormsg['serialno'] = "0"

  index = '<ts>'
  if rcv.find(index) >= 0:
    timestamp = int((rcv[rcv.find(index)+4:rcv.find('<',rcv.find(index)+4)]))
    errormsg['timestamp'] = timestamp
    errormsg['datetime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp))
  else:
    errormsg['timestamp'] = "0"
    errormsg['datetime'] = "0"

  index = '<code>'
  if rcv.find(index) >= 0:
    errormsg['code'] = str((rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index)+6)]))
  else:
    errormsg['code'] = "0"

  index = '<state>'
  if rcv.find(index) >= 0:
    errormsg['state'] = str((rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index)+7)]))
  else:
    errormsg['state'] = "0"

  index = '<short>'
  if rcv.find(index) >= 0:
    errormsg['short'] = str((rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index)+7)]))
  else:
    errormsg['short'] = "0"

  index = '<long>'
  if rcv.find(index) >= 0:
    errormsg['long'] = str((rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index)+6)]))
  else:
    errormsg['long'] = "0"

  index = '<type>'
  if rcv.find(index) >= 0:
    errormsg['type'] = str((rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index)+6)]))
  else:
    errormsg['type'] = "0"

  index = '<actstate>'
  if rcv.find(index) >= 0:
    errormsg['actstate'] = str((rcv[rcv.find(index)+10:rcv.find('<',rcv.find(index)+10)]))
  else:
    errormsg['actstate'] = "0"

  # print("JSON Error: " + json.dumps(errormsg, sort_keys=True)) # sort_keys=True
  logging.debug("JSON Error: " + json.dumps(errormsg, sort_keys=True)) # sort_keys=True
  return errormsg

def sendbytes2portal(server_addr,block):
    #Sende zu Sitelink/Refu-Log Portal

    daten = 0

    logging.debug("Server address: " + str(server_addr))
    try:
      client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      client_socket.settimeout(5)
      client_socket.connect(server_addr)
      client_socket.send(block)#Sende empfangene Daten von WR zu Portal
      # print('Sende Daten zu ' + str(server_addr) + ':\r\n' + bytes2string(block) + '\r\n')
      # logstring += 'Sende Daten zu ' + str(server_addr) + ':\r\n' + bytes2string(block) + '\r\n'
      daten = client_socket.recv(1024)#Empfange Rückmeldung von Portal
      datenstring = bytes2string(daten)
      #print(datenstring)
      # print('Empfange Daten von ' + str(server_addr) + ':\r\n' + str(datenstring) + '\r\n')
      # logstring += 'Empfange Daten von ' + str(server_addr) + ':\r\n' + str(datenstring) + '\r\n'
    except BaseException as e:
      #print(str(e) + '\r\n')
      #logstring += str(e) + '\r\n' + 'Sending data to ' + str(server_addr) + ' failed!' + '\r\n'
      logging.error(str(e) + '\r\n' + 'Sending data to ' + str(server_addr) + ' failed!')

    client_socket.close()
    del client_socket

    return daten

def getokmsg():
    tz = pytz.timezone('Europe/Berlin')
    berlin_now = datetime.now(tz)

    sendcontent = ('<?xml version="1.0" encoding="utf-8"?>\r\n'
      +'<string xmlns="InverterService">OK</string>')

    return ('HTTP/1.1 200 OK\r\n'
    +'Date: ' + berlin_now.strftime('%a, %d %b %Y %X GMT') +'\r\n'
    +'Content-Type: text/xml; charset=utf-8\r\n'
    +'Content-Length: ' + str(len(sendcontent)) + '\r\n'
    +'Connection: keep-alive\r\n'
    +'X-Frame-Options: SAMEORIGIN\r\n'
    +'\r\n'
    +sendcontent)

def gettimemsg():
  tz = pytz.timezone('Europe/Berlin')
  berlin_now = datetime.now(tz)
  try:
    sendcontent = ('<?xml version="1.0" encoding="utf-8"?>\r\n'
                   +'<string xmlns="InverterService">&lt;crqr&gt;&lt;c n="SETINVERTERTIME" i="0"&gt;&lt;p n="date" t="3"&gt;'
                   +berlin_now.strftime('%d.%m.%Y %X')
                   +'&lt;/p&gt;&lt;/c&gt;&lt;/crqr&gt;</string>')
    return ('HTTP/1.1 200 OK\r\n'
    +'Date: ' + berlin_now.strftime('%a, %d %b %Y %X GMT') +'\r\n'
    +'Content-Type: text/xml; charset=utf-8\r\n'
    +'Content-Length: ' + str(len(sendcontent)) + '\r\n'
    +'Connection: keep-alive\r\n'
    +'X-Frame-Options: SAMEORIGIN\r\n'
    +'\r\n'
    + sendcontent)
  except BaseException as e:
    #print('Irgendwas bei der Erstellung der Antwortnachricht zum Setzen der Uhrzeit ist schief gelaufen. gettimemsg()')
    logging.error("Irgendwas bei der Erstellung der Antwortnachricht zum Setzen der Uhrzeit ist schief gelaufen. gettimemsg()")
    return getokmsg() # Wenn Zeit holen nicht möglich, nur Ok message schicken

def on_connect(client, userdata, flags, rc):
  logging.info("MQTT client connected: " + str(client.is_connected()))
  logging.info("Connected with result code: " + str(rc))

  # Subscribing in on_connect() means that if we lose the connection and
  # reconnect then subscriptions will be renewed.
  # client.subscribe("$SYS/#")

#Hier startet Main prg
def main():
  global rawdataserver
  global server_socket

  #Init TCP-Server
  server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #Bei Neustart wiederverwenden des Sockets ermöglichen
  server_socket.bind((server_ip, server_port)) # Keine IP angeben ==> Server lauscht auf allen zugewiesenen IP Adressen
  server_socket.listen(5) # Socket beobachten

  # Init MQTT client
  mqttclient = mqtt.Client()
  mqttclient.on_connect = on_connect
  mqttclient.username_pw_set("logsinvert", "Spiel-Konzernumsatz-Zielen-Kurz")

  mqttclient.connect("51.15.196.38", 1883)
  mqttclient.loop_start()

  #print(socket.gethostbyname(socket.gethostname()))
  while True:
    ret = mqttclient.publish("seimerich/pv/neuerstall/status", "Warte auf Daten...");
    logging.debug("Return of mqtt publish: " + str(ret) + "\r\n")

    logging.debug('Listen for Data')
    rcvdatenstring = ''
    rcvok1 = ''
    rcvok2 = ''
    block = string2bytes('')
    rcvbytes = string2bytes('')
    client_serving_socket, addr = server_socket.accept()
    client_serving_socket.settimeout(1)

    for ls in lsInverters:
      logging.debug(ls.serialno)
  
    while True:
      try:
        rcvbytes = string2bytes('') # clear buffer for reading
        rcvbytes = client_serving_socket.recv(1024) #Daten empfangen
        logging.debug("Length rcvbytes: " + str(len(rcvbytes)))
      except BaseException as e:
        #print(str(e) + '\r\n')
        logging.debug(str(e) + '\r\n' + 'Error während lesen von Socket!' + '\r\n' + str(rcvbytes) + '\r\n')
      block = block + rcvbytes # compose message from several readings

      rcvdatenstring = bytes2string(block) # convert received composed message to a string

      # typically the message we are looking for looks like:
      # first execution of recv() brings the following part of the message (header)
      # Daten von WR empfangen: POST /sinvertwebmonitor/InverterService/InverterService.asmx/CollectInverterData HTTP/1.1
      # Host: www.automation.siemens.com
      # Content-Type: application/x-www-form-urlencoded
      # Content-Length: 187

      # second execution of recv() brings the following part of the message (body)
      # xmlData=<re><m>502DF400489C</m><s>LBAN02261010322</s><e><ts>1604741706</ts><code>a010c</code><state>2</state><short>0</short><long>2048</long><type>8</type><actstate>6</actstate></e></re>
      # then we should stop reading. We could also use Content-length. That would probably be cleaner.

      rcvok1 = rcvdatenstring.find('sinvertwebmonitor') # check if message contains "sinvertwebmonitor"
      rcvok2 = rcvdatenstring.find('xmlData') # check of message contains "xmlData"
      logging.debug("rcvok1: " + str(rcvok1) + " rcvok2: " + str(rcvok2))
      if ((rcvok1 >= 0 and rcvok2 >= 0) or len(rcvbytes) <= 0): # falls Nachricht vollständig gelesen (rcvok1/2 = 0k) oder keine Daten mehr gelesen werden -> break
        break

    # Falls rcvok1 und rcvok2 dann gehen wir davon aus, dass Daten vom Wechselrichter kommen.
    if (rcvok1 >= 0 and rcvok2 >= 0):
      logging.debug("Daten von WR empfangen: \r\n" + rcvdatenstring + '\r\n')

      # Daten an GreenSynergy Portal senden
      logging.debug("Daten an GreenSynergy Portal senden. \r\n")
      for adress in rawdataserver:
        reply = sendbytes2portal(adress, block)
      logging.debug("Daten von GreenSynergy Portal enthalten: \r\n" + bytes2string(reply) + "\r\n")

      # Empfangene Daten verarbeiten
      if rcvdatenstring.find('<rd') >= 0: # Daten empfangen
        logging.debug('Empfangene Nachricht enthält Betriebsdaten des Wechselrichters <rd>\r\n')
        # print('Daten, die wir an WR senden würden: \r\n' + getokmsg() + "\r\n")
        client_serving_socket.send(string2bytes(getokmsg()))
        jsondata = decodedata(rcvdatenstring)
        ret = mqttclient.publish("seimerich/pv/neuerstall/" + str(jsondata['serialno']) + "/data", json.dumps(jsondata, sort_keys=True));
        logging.debug("Return of mqtt publish: " + str(ret) + "\r\n")

        el = [x for x in lsInverters if x.serialno == jsondata['serialno']] 
        if len(el) > 0:
          logging.debug("Inverter already in list 1")
          inverter = el[0]
        else:
          logging.info("Adding new inverter to list: " + str(jsondata['serialno']))
          inverter = Inverter(jsondata['serialno'])
          lsInverters.append(inverter)

        inverter.logDataMSG(json.dumps(jsondata, sort_keys=True))

        try:
          inverter.logfile_data.flush()
        except FileNotFoundError:
          logging.error("Flush went wrong. Logfile not accessible.")

      elif rcvdatenstring.find('<re') >= 0: # Fehlermeldung empfangen
        logging.debug('Empfangene Nachricht enthält Fehlermeldung des Wechselrichters <re>\r\n')
        # print('Daten, die wir an WR senden würden: \r\n' + getokmsg() + "\r\n")
        client_serving_socket.send(string2bytes(getokmsg()))
        jsondata = decodeerr(rcvdatenstring)
        ret = mqttclient.publish("seimerich/pv/neuerstall/" + str(jsondata['serialno']) + "/error", json.dumps(jsondata, sort_keys=True));
        logging.debug("Return of mqtt publish: " + str(ret) + "\r\n")

        el = [x for x in lsInverters if x.serialno == jsondata['serialno']] 
        if len(el) > 0:
          logging.debug("Inverter already in list 2")
          inverter = el[0]
        else:
          logging.info("Adding new inverter to list: " + str(jsondata['serialno']))
          inverter = Inverter(jsondata['serialno'])
          lsInverters.append(inverter)

        inverter.logErrorMSG(json.dumps(jsondata, sort_keys=True))

        try:
          inverter.logfile_error.flush()
        except FileNotFoundError:
          logging.error("Flush went wrong. Logfile not accessible.")

      elif rcvdatenstring.find('<crq') >= 0: # Steuerungsdaten empfangen # Wenn Steuerdaten empfangen, dann in Uhrzeit setzen
        # Dem WR aktuelle Uhrzeit schicken schicken
        logging.debug('Empfangene Nachricht enthält Steuerungsanfrage des Wechselrichters <crq>\r\n')
        # print('Daten, die wir an WR senden würden: \r\n' + gettimemsg() + "\r\n")
        client_serving_socket.send(string2bytes(gettimemsg()))

      else: # Serveranfragen, die vom Wechselrichter kommen, aber nicht interpretiert werden kann
        logging.debug('Falsches Datenformat empfangen!\r\n')
        logging.debug(rcvdatenstring)
        # Dem WR eine OK Nachricht schicken
        client_serving_socket.send(string2bytes(getokmsg()))
        ret = mqttclient.publish("seimerich/pv/neuerstall/Unbekannte_Wechselrichterdaten", str(rcvdatenstring));
        logging.debug("Return of mqtt publish: " + str(ret) + "\r\n")

    else: # Serveranfragen, die nicht von den Wechselrichtern stammen
      logging.debug("Andere Daten empfangen: " + rcvdatenstring + '\r\n')
      #ret = mqttclient.publish("seimerich/pv/neuerstall/Unbekannte_Daten", str(rcvdatenstring));
      #logging.debug("Return of mqtt publish: " + str(ret) + "\r\n")

    # Verbindung schließen
    client_serving_socket.close()
    del client_serving_socket

#Hauptschleife
while True:
  try:
    logging.debug("Start of program")
    main()
  except BaseException as e:#bei einer Exception Verbindung schließen und neu starten
    logging.error(str(e) + '\r\n')
    server_socket.close()
    del server_socket
  time.sleep(10)#10s warten
#ServerEnde
