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
from datetime import datetime
from collections import OrderedDict

minpythonversion = 0x3020000
if sys.hexversion < minpythonversion:
  print('Python version ' + str(sys.version) + ' is too old, please use Python version 3.2 or newer!')
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

# Benutzung auf eigene Gefahr! Keine Garantie/Gewaehrleistung/Schadenersatzansprueche.

# TODO:
# - Exceptionhandling optimieren
# - Codeoptimierungen...
# - Mailversand wenn Stoerungen auftreten
# - Stoerungsnummern wandeln in Stoerungstext


#Define Pfad für CSV-Files, sind den eigenen Bedürfnissen anzupassen 
#datalogfile = "E:\" + time.strftime("\%Y_%m_DataSinvert") + '.csv' #Beispiel für Windows
#errlogfile = "E:\" + time.strftime("\%Y_%m_ErrSinvert") + '.csv'#Beispiel für Windows

datalogpath = "./" # /home/pi/
errlogpath = "./" # /home/pi/
loggingpath = "./" # /home/pi/
datalogfilename = 'DataSinvert.csv'
errlogfilename = 'ErrSinvert.csv'
loggingfilename = 'LoggingSinvert.txt'

#Logfilepfad initialisieren
datalogfile = datalogpath + time.strftime("%Y_%m_") + datalogfilename
errlogfile = errlogpath + time.strftime("%Y_%m_") + errlogfilename
loggingfile = loggingpath + time.strftime("%Y_%m_") + loggingfilename

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

#init logstring
logstring = ''

class Inverter:
  def __init__(self, serialno):  
    self.serialno = serialno
    self.logfile_data = ""
    self.logfile_data_name = "" # LBAN02261010321_data_YEAR_Month e.g. LBAN02261010321_data_2021_03
    self.logfile_error = ""
    self.logfile_error_name = "" # LBAN02261010321_error_YEAR_Month e.g. LBAN02261010321_error_2021_03
    self.setLogfiles()

  def logDataMSG(self, msg):
    print("Trying to log data... ")

    actualFilename = self.composeActualFilename("data")
    # print("actualFilename: ", actualFilename)

    if actualFilename == self.logfile_data_name:
      # print("Actual filename ok...")
      self.logfile_data.write(msg + "\n")
    else:
      # print("create new file...")
      try:
        # print("close existing file...")
        self.logfile_data.close()
      except FileNotFoundError:
        print("Data logfile not accessible")
      setLogfiles()
      self.logfile_data.write(msg + "\n")
      
    self.logfile_data.flush()

    print("Logged in data logfile.")

  def logErrorMSG(self, msg):
    print("Trying to log error... ")

    actualFilename = self.composeActualFilename("error")
    if actualFilename == self.logfile_error_name:
      self.logfile_error.write(msg + "\n")
    else:
      try:
        self.logfile_error.close()
      except FileNotFoundError:
        print("Error logfile not accessible")
      setLogfiles()
      self.logfile_error.write(msg + "\n")

    self.logfile_error.flush()

    print("Logged in error logfile.")

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

  def setLogfiles(self):
    actualFilename = self.composeActualFilename("data")
    try:
      f = open(actualFilename, "a+") # if file exists, append data, if not create a new one
      self.logfile_data = f
      self.logfile_data_name = actualFilename
    except FileNotFoundError:
      print("Data logfile not accessible")

    actualFilename = self.composeActualFilename("error")
    try:
      f = open(actualFilename, "a+") # if file exists, append data, if not create a new one
      self.logfile_error = f
      self.logfile_error_name = actualFilename
    except FileNotFoundError:
      print("Error logfile not accessible")


lsInverters = []


def byteorder():
  global logstring
  return sys.byteorder

def standard_encoding():
  return sys.getdefaultencoding()

def standardausgabe_encoding():
  global logstring
  return sys.stdout.encoding

def string2bytes(text):
  global logstring
  return bytes(text, "cp1252")

def bytes2string(bytes):
  global logstring
  return str(bytes, "cp1252")

def converthex2float(hexval):
  global logstring
  #print(hexval)
  try:
    return round(struct.unpack('>f', struct.pack('>I', int(float.fromhex(hexval))))[0],2)
  except BaseException as e:
    print(str(e) + '\r\n')
    logstring += str(e) + '\r\n' + 'Error while convert hex to float failed! hexvalue = ' + str(hexval) + '\r\n'
    return 0

def converthex2int(hexval):
  global logstring
  #print(hexval)
  try:
    return struct.unpack('>i', struct.pack('>I', int(float.fromhex(hexval))))[0]
  except BaseException as e:
    print(str(e) + '\r\n')
    logstring += str(e) + '\r\n' + 'Error while convert hex to int failed! hexvalue = ' + str(hexval) + '\r\n'
    return 0

def initdatalogfile(datalogfile):
  global logstring
  string = []

  string.append('MAC-Adresse')
  string.append('Seriennummer')
  string.append('Zeitstempel')
  string.append('Loggerinterval')
  string.append('AC Momentanleistung [W]')
  string.append('AC Netzspannung [V]')
  string.append('AC Strom [A]')
  string.append('AC Frequenz [Hz]')
  string.append('DC Momentanleistung [W]')
  string.append('DC-Spannung [V]')
  string.append('DC-Strom [A]')
  string.append('Temperatur 1 Kuehlkoerper rechts [°C]')
  string.append('Temperatur 2 innen oben links [°C]')
  string.append('Sensor 1 Messwert, Einstrahlung [W/m^2]')
  string.append('Sensor 2 Messwert, Modultemperatur [°C]')
  string.append('Tagesertrag [kwh]')
  string.append('Status')
  string.append('Gesamtertrag [kwh]')
  string.append('Betriebsstunden [h]')
  string.append('scheinbar nur ältere FW?')
  string.append('"neuere" FW: 100.0% Leistungsbeschräkung [%]')
  string.append('"neuere" FW, vielleicht: 0.0 kWh Tagessonnenenergie')
  returnval = (str(string).replace("', '",';').replace("['",'').replace("']",'\r\n'))
  f = open(datalogfile, 'a')
  f.write(returnval)
  f.close()

def initerrlogfile(errlogfile):
  global logstring
  string = []

  string.append('MAC-Adresse')
  string.append('Seriennummer')
  string.append('Zeitstempel')
  string.append('Errorcode')
  string.append('State')
  string.append('Short')
  string.append('Long')
  string.append('Type')
  string.append('Actstate')
  returnval = (str(string).replace("', '",';').replace("['",'').replace("']",'\r\n'))
  f = open(errlogfile, 'a')
  f.write(returnval)
  f.close()

# def writeDataFile(data):
#   serialno = data['serialno']

#   for i, inverter in enumerate(lsLogFiles):
#     if serialno in inverter:
#       # check if file exits -> write to file
#     else

#   print("write data file")

# def writeErrorFile(path):
#   print("write error file")

def decodedata(rcv):#Daten decodieren
  global logstring
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
    dataset['loggerinterval'] = str((rcv[rcv.find(index)+5:rcv.find('"',rcv.find(index)+5)]))
  else:
    dataset['loggerinterval'] = 0

  index = 'i="1"'
  if rcv.find(index) >= 0:
    acleistung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['AC_power'] = acleistung
  else:
    operationaldata['AC_power'] = 0

  index = 'i="2"'
  if rcv.find(index) >= 0:
    acspannung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['AC_voltage'] = acspannung
  else:
    operationaldata['AC_voltage'] = 0

  index = 'i="3"'
  if rcv.find(index) >= 0:
    acstrom = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['AC_current'] = acstrom
  else:
    operationaldata['AC_current'] = 0

  index = 'i="4"'
  if rcv.find(index) >= 0:
    acfrequenz = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['frequency'] = acfrequenz
  else:
    operationaldata['frequency'] = 0

  index = 'i="5"'
  if rcv.find(index) >= 0:
    dcleistung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['DC_power'] = dcleistung
  else:
    operationaldata['DC_power'] = 0

  index = 'i="6"'
  if rcv.find(index) >= 0:
    dcspannung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['DC_voltage'] = dcspannung
  else:
    operationaldata['DC_voltage'] = 0

  index = 'i="7"'
  if rcv.find(index) >= 0:
    dcstrom = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['DC_current'] = dcstrom
  else:
    operationaldata['DC_current'] = 0

  index = 'i="8"'
  if rcv.find(index) >= 0:
    temp1 = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['temperature_left'] = temp1
  else:
    operationaldata['temperature_left'] = 0

  index = 'i="9"'
  if rcv.find(index) >= 0:
    temp2 = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['temperature_right'] = temp2
  else:
    operationaldata['temperature_right'] = 0

  index = 'i="A"'
  if rcv.find(index) >= 0:
    einstrahlung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])) + ''
    operationaldata['irridation'] = einstrahlung
  else:
    operationaldata['irridation'] = 0

  index = 'i="B"'
  if rcv.find(index) >= 0:
    modultemp = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])) + ''
    operationaldata['temperature_pvpanel'] = modultemp
  else:
    operationaldata['temperature_pvpanel'] = 0

  index = 'i="C"'
  if rcv.find(index) >= 0:
    tagesertrag = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['daily_yield'] = tagesertrag
  else:
    operationaldata['daily_yield'] = 0

  index = 'i="D"'
  if rcv.find(index) >= 0:
    status = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    operationaldata['status'] = status
  else:
    operationaldata['status'] = 0

  index = 'i="E"'
  if rcv.find(index) >= 0:
    gesamtertrag = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['yield'] = gesamtertrag
  else:
    operationaldata['yield'] = 0

  index = 'i="F"'
  if rcv.find(index) >= 0:
    betriebsstunden = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    operationaldata['operating_hours'] = betriebsstunden
  else:
    operationaldata['operating_hours'] = 0

  index = 'i="10"'
  if rcv.find(index) >= 0:
    operationaldata['undefined1'] = str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10)
  else:
    operationaldata['undefined1'] = 0

  index = 'i="12"'
  if rcv.find(index) >= 0:
    leistungsbesch = str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10)
    operationaldata['undefined2'] = leistungsbesch
  else:
    operationaldata['undefined2'] = 0

  index = 'i="11"'
  if rcv.find(index) >= 0:
    tagessonnenenergie = str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10)
    operationaldata['undefined3'] = tagessonnenenergie
  else:
    operationaldata['undefined3'] = 0

  # returnval = (str(string).replace("', '",';').replace("['",'').replace("']",'\r\n').replace(".",','))
  # logstring += 'Decoded data:' + '\r\n' + returnval + '\r\n'
  # print(returnval)
  dataset['operationaldata'] = operationaldata
  print("JSON: " + json.dumps(dataset, sort_keys=True)) # sort_keys=True
  return dataset

def decodeerr(rcv):#Störungen decodieren

  #xmlData=<re><m>502DF40048AF</m><s>LBAN02261010321</s><e><ts>1612105645</ts><code>a010c</code><state>2</state><short>0</short><long>2048</long><type>8</type><actstate>6</actstate></e></re>

  global logstring
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
  # returnval = (str(string).replace("', '",';').replace("['",'').replace("']",'\r\n').replace(".",','))
  # print(returnval)
  # logstring += 'Decoded errors:' + '\r\n' + returnval + '\r\n'
  print("JSON Error: " + json.dumps(errormsg, sort_keys=True)) # sort_keys=True
  return errormsg

def sendbytes2portal(server_addr,block):
    global logstring
    #Sende zu Sitelink/Refu-Log Portal

    daten = 0

    print(server_addr)
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
      print(str(e) + '\r\n')
      logstring += str(e) + '\r\n' + 'Sending data to ' + str(server_addr) + ' failed!' + '\r\n'

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
    print('Irgendwas bei der Erstellung der Antwortnachricht zum Setzen der Uhrzeit ist schief gelaufen. gettimemsg()')
    return getokmsg() # Wenn Zeit holen nicht möglich, nur Ok message schicken

def on_connect(client, userdata, flags, rc):
  print("MQTT client connected: " + str(client.is_connected()))
  print("Connected with result code "+str(rc))

  # Subscribing in on_connect() means that if we lose the connection and
  # reconnect then subscriptions will be renewed.
  # client.subscribe("$SYS/#")

#Hier startet Main prg
def main():
  global logstring
  global rawdataserver
  global server_socket

  #Init TCP-Server
  server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #Bei Neustart wiederverwenden des Sockets ermöglichen
  server_socket.bind((server_ip, server_port)) # Keine IP angeben ==> Server lauscht auf allen zugewiesenen IP Adressen
  server_socket.listen(5) # Socket beobachten

  loggingfile = loggingpath + time.strftime("%Y_%m_") + loggingfilename
  logstring = ""

  # Init MQTT client
  mqttclient = mqtt.Client()
  mqttclient.on_connect = on_connect
  mqttclient.username_pw_set("logsinvert", "Spiel-Konzernumsatz-Zielen-Kurz")

  mqttclient.connect("51.15.196.38", 1883)
  mqttclient.loop_start()


  #print(socket.gethostbyname(socket.gethostname()))
  while True:
    ret = mqttclient.publish("seimerich/pv/neuerstall/status", "Warte auf Daten...");
    print("Return of mqtt publish: " + str(ret) + "\r\n")

    for _inverter in lsInverters:
      try:
        _inverter.logfile_error.flush()
      except FileNotFoundError:
        print("Flush went wrong. Logfile not accessible.")

    print('Listen for Data')
    logstring += "Listen for Data"
    rcvdatenstring = ''
    rcvok1 = ''
    rcvok2 = ''
    block = string2bytes('')
    rcvbytes = string2bytes('')
    client_serving_socket, addr = server_socket.accept()
    client_serving_socket.settimeout(1)

    for ls in lsInverters:
      print(ls.serialno)
  
    while True:
      try:
        rcvbytes = string2bytes('') # clear buffer for reading
        rcvbytes = client_serving_socket.recv(1024) #Daten empfangen
        print("Length rcvbytes: " + str(len(rcvbytes)))
        logstring += "Length rcvbytes: " + str(len(rcvbytes)) + "\r\n"
        # print(bytes2string(rcvbytes) + '\r\n')
      except BaseException as e:
        #print(str(e) + '\r\n')
        print(str(e) + '\r\n' + 'Error während lesen von Socket!' + '\r\n' + str(rcvbytes) + '\r\n')
        logstring += str(e) + '\r\n' + 'Error während lesen von Socket!' + '\r\n' + str(rcvbytes) + '\r\n'
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
      print("rcvok1: " + str(rcvok1) + " rcvok2: " + str(rcvok2))
      logstring += "rcvok1: " + str(rcvok1) + " rcvok2: " + str(rcvok2) + "\r\n"
      if ((rcvok1 >= 0 and rcvok2 >= 0) or len(rcvbytes) <= 0): # falls Nachricht vollständig gelesen (rcvok1/2 = 0k) oder keine Daten mehr gelesen werden -> break
        break

    # Falls rcvok1 und rcvok2 dann gehen wir davon aus, dass Daten vom Wechselrichter kommen.
    if (rcvok1 >= 0 and rcvok2 >= 0):
      print("Daten von WR empfangen: \r\n" + rcvdatenstring + '\r\n')
      logstring += "Daten von WR empfangen: " + rcvdatenstring + '\r\n'

      # Daten an GreenSynergy Portal senden
      print("Daten an GreenSynergy Portal senden. \r\n")
      logstring += "Daten an GreenSynergy Portal senden. \r\n"
      for adress in rawdataserver:
        reply = sendbytes2portal(adress, block)
      print("Daten von GreenSynergy Portal enthalten: \r\n" + bytes2string(reply) + "\r\n")
      logstring += "Daten von GreenSynergy Portal enthalten: \r\n" + bytes2string(reply) + "\r\n"

      # Empfangene Daten verarbeiten
      if rcvdatenstring.find('<rd') >= 0: # Daten empfangen
        print('Empfangene Nachricht enthält Betriebsdaten des Wechselrichters <rd>\r\n')
        # print('Daten, die wir an WR senden würden: \r\n' + getokmsg() + "\r\n")
        client_serving_socket.send(string2bytes(getokmsg()))
        jsondata = decodedata(rcvdatenstring)
        ret = mqttclient.publish("seimerich/pv/neuerstall/" + str(jsondata['serialno']) + "/data", json.dumps(jsondata, sort_keys=True));
        print("Return of mqtt publish: " + str(ret) + "\r\n")

        el = [x for x in lsInverters if x.serialno == jsondata['serialno']] 
        if len(el) > 0:
          print("Inverter already in list")
          inverter = el[0]
        else:
          print("Adding new inverter to list")
          inverter = Inverter(jsondata['serialno'])
          lsInverters.append(inverter)

        inverter.logDataMSG(json.dumps(jsondata, sort_keys=True))

      elif rcvdatenstring.find('<re') >= 0: # Fehlermeldung empfangen
        print('Empfangene Nachricht enthält Fehlermeldung des Wechselrichters <re>\r\n')
        # print('Daten, die wir an WR senden würden: \r\n' + getokmsg() + "\r\n")
        client_serving_socket.send(string2bytes(getokmsg()))
        jsondata = decodeerr(rcvdatenstring)
        ret = mqttclient.publish("seimerich/pv/neuerstall/" + str(jsondata['serialno']) + "/error", json.dumps(jsondata, sort_keys=True));
        print("Return of mqtt publish: " + str(ret) + "\r\n")

        el = [x for x in lsInverters if x.serialno == jsondata['serialno']] 
        if len(el) > 0:
          print("Inverter already in list")
          inverter = el[0]
        else:
          print("Adding new inverter to list")
          inverter = Inverter(jsondata['serialno'])
          lsInverters.append(inverter)

        inverter.logErrorMSG(json.dumps(jsondata, sort_keys=True))

      elif rcvdatenstring.find('<crq') >= 0: # Steuerungsdaten empfangen # Wenn Steuerdaten empfangen, dann in Uhrzeit setzen
        # Dem WR aktuelle Uhrzeit schicken schicken
        print('Empfangene Nachricht enthält Steuerungsanfrage des Wechselrichters <crq>\r\n')
        # print('Daten, die wir an WR senden würden: \r\n' + gettimemsg() + "\r\n")
        client_serving_socket.send(string2bytes(gettimemsg()))

      else: # Serveranfragen, die vom Wechselrichter kommen, aber nicht interpretiert werden kann
        print('Falsches Datenformat empfangen!\r\n')
        print(rcvdatenstring)
        # logstring += 'Falsches Datenformat empfangen!\r\n' + rcvdatenstring[rcvdatenstring.find('xmlData'):] + '\r\n'
        # Dem WR eine OK Nachricht schicken
        client_serving_socket.send(string2bytes(getokmsg()))
        ret = mqttclient.publish("seimerich/pv/neuerstall/Unbekannte_Wechselrichterdaten", str(rcvdatenstring));
        print("Return of mqtt publish: " + str(ret) + "\r\n")

    else: # Serveranfragen, die nicht von den Wechselrichtern stammen
      print("Andere Daten empfangen: " + rcvdatenstring + '\r\n')
      logstring += "Andere Daten empfangen: " + rcvdatenstring + '\r\n'
      ret = mqttclient.publish("seimerich/pv/neuerstall/Unbekannte_Daten", str(rcvdatenstring));
      print("Return of mqtt publish: " + str(ret) + "\r\n")

    # Verbindung schließen
    client_serving_socket.close()
    del client_serving_socket

    #Daten in Loggingfile schreiben
    f = open(loggingfile, 'a')
    f.write(logstring)
    f.close()
    logstring = ''

#Hauptschleife
while True:
  try:
    main()
  except BaseException as e:#bei einer Exception Verbindung schließen und neu starten
    print(str(e) + '\r\n')
    f = open(loggingfile, 'a')
    f.write(logstring)
    f.close()
    logstring = ''
    server_socket.close()
    del server_socket
  time.sleep(10)#10s warten
#ServerEnde
