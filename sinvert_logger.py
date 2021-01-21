#!/usr/bin/python3
# -*- coding: utf-8 -*-
import socket
import sys
import struct
import time
import pickle
import json
import pytz
from datetime import datetime

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
macaddr,endmacaddr = '<m>','</m>'#für ältere firmwares

#firmware,endfirmware = 's="','"'#für neuere firmwares
firmware,endfirmware = '<s>','</s>'#für ältere firmwares

server_ip = '' #IP- des Raspi angeben, wenn keine IP angeben wird ==> Raspi lauscht auf allen zugewiesenen IP Adressen
server_port = 81 #Port auf dem das prg am raspi lauscht

#Server, an dessen die Daten 1:1 durchgereicht werden, Format: [('ipserver1',portserver1),('ipserver2',portserver2),usw...]
#Es k?nnen beliebig viele Server angegeben werden, diese werden in einer Schleife abgearbeitet
#Wenn an keine Server weitergereicht werden soll, dann: rawdataserver = []
rawdataserver = [('5.45.98.160', 80)]

#init logstring
logstring = ''

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

def decodedata(rcv):#Daten decodieren
  global logstring
  string = []

  index = macaddr
  endindex = endmacaddr
  if rcv.find(index) >= 0:
    string.append(str(rcv[rcv.find(index)+3:rcv.find(endindex,rcv.find(index)+3)]))
  else:
    string.append('0')
  index = firmware
  endindex = endfirmware
  if rcv.find(index) >= 0:
    string.append(str(rcv[rcv.find(index)+3:rcv.find(endindex,rcv.find(index)+3)]))
  else:
    string.append('0')
  index = 't="'
  if rcv.find(index) >= 0:
    timestamp = int((rcv[rcv.find(index)+3:rcv.find('"',rcv.find(index)+3)]))
    string.append(time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(timestamp)))
  else:
    string.append('0')
  index = '" l="'
  if rcv.find(index) >= 0:
    string.append(str((rcv[rcv.find(index)+5:rcv.find('"',rcv.find(index)+5)])))
  else:
    string.append('0')
  index = 'i="1"'
  if rcv.find(index) >= 0:
    acleistung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(acleistung)
  else:
    string.append('0')
  index = 'i="2"'
  if rcv.find(index) >= 0:
    acspannung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(acspannung)
  else:
    string.append('0')
  index = 'i="3"'
  if rcv.find(index) >= 0:
    acstrom = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(acstrom)
  else:
    string.append('0')
  index = 'i="4"'
  if rcv.find(index) >= 0:
    acfrequenz = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(acfrequenz)
  else:
    string.append('0')
  index = 'i="5"'
  if rcv.find(index) >= 0:
    dcleistung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(dcleistung)
  else:
    string.append('0')
  index = 'i="6"'
  if rcv.find(index) >= 0:
    dcspannung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(dcspannung)
  else:
    string.append('0')
  index = 'i="7"'
  if rcv.find(index) >= 0:
    dcstrom = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(dcstrom)
  else:
    string.append('0')
  index = 'i="8"'
  if rcv.find(index) >= 0:
    temp1 = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    string.append(temp1)
  else:
    string.append('0')
  index = 'i="9"'
  if rcv.find(index) >= 0:
    temp2 = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    string.append(temp2)
  else:
    string.append('0')
  index = 'i="A"'
  if rcv.find(index) >= 0:
    einstrahlung = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])) + ''
    string.append(einstrahlung)
  else:
    string.append('0')
  index = 'i="B"'
  if rcv.find(index) >= 0:
    modultemp = str(converthex2float(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])) + ''
    string.append(modultemp)
  else:
    string.append('0')
  index = 'i="C"'
  if rcv.find(index) >= 0:
    tagesertrag = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    string.append(tagesertrag)
  else:
    string.append('0')
  index = 'i="D"'
  if rcv.find(index) >= 0:
    status = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))]))
    string.append(status)
  else:
    string.append('0')
  index = 'i="E"'
  if rcv.find(index) >= 0:
    gesamtertrag = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    string.append(gesamtertrag)
  else:
    string.append('0')
  index = 'i="F"'
  if rcv.find(index) >= 0:
    betriebsstunden = str(converthex2int(rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index))])/10)
    string.append(betriebsstunden)
  else:
    string.append('0')
  index = 'i="10"'
  if rcv.find(index) >= 0:
    string.append(str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10))
  else:
    string.append('0')
  index = 'i="12"'
  if rcv.find(index) >= 0:
    leistungsbesch = str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10)
    string.append(leistungsbesch)
  else:
    string.append('0')
  index = 'i="11"'
  if rcv.find(index) >= 0:
    tagessonnenenergie = str(converthex2int(rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index))])/10)
    string.append(tagessonnenenergie)
  else:
    string.append('0')
  returnval = (str(string).replace("', '",';').replace("['",'').replace("']",'\r\n').replace(".",','))
  logstring += 'Decoded data:' + '\r\n' + returnval + '\r\n'
  print(returnval)
  return returnval

def decodeerr(rcv):#Störungen decodieren
  global logstring
  string = []

  index = macaddr
  if rcv.find(index) >= 0:
    string.append(str(rcv[rcv.find(index)+3:rcv.find('"',rcv.find(index)+3)]))
  else:
    string.append('0')
  index = firmware
  if rcv.find(index) >= 0:
    string.append(str(rcv[rcv.find(index)+3:rcv.find('"',rcv.find(index)+3)]))
  else:
    string.append('0')
  index = 't="'
  if rcv.find(index) >= 0:
    string.append(time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(int((rcv[rcv.find(index)+3:rcv.find('"',rcv.find(index)+3)])))))
  else:
    string.append('0')
  index = '<code>'
  if rcv.find(index) >= 0:
    string.append(str((rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index)+6)])))
  else:
    string.append('0')
  index = '<state>'
  if rcv.find(index) >= 0:
    string.append(str((rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index)+7)])))
  else:
    string.append('0')
  index = '<short>'
  if rcv.find(index) >= 0:
    string.append(str((rcv[rcv.find(index)+7:rcv.find('<',rcv.find(index)+7)])))
  else:
    string.append('0')
  index = '<long>'
  if rcv.find(index) >= 0:
    string.append(str((rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index)+6)])))
  else:
    string.append('0')
  index = '<type>'
  if rcv.find(index) >= 0:
    string.append(str((rcv[rcv.find(index)+6:rcv.find('<',rcv.find(index)+6)])))
  else:
    string.append('0')
  index = '<actstate>'
  if rcv.find(index) >= 0:
    string.append(str((rcv[rcv.find(index)+10:rcv.find('<',rcv.find(index)+10)])))
  else:
    string.append('0')
  returnval = (str(string).replace("', '",';').replace("['",'').replace("']",'\r\n').replace(".",','))
  print(returnval)
  logstring += 'Decoded errors:' + '\r\n' + returnval + '\r\n'
  return returnval

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

  #print(socket.gethostbyname(socket.gethostname()))
  while True:
    print('Listen for Data')
    logstring += "Listen for Data"
    rcvdatenstring = ''
    rcvok1 = ''
    rcvok2 = ''
    block = string2bytes('')
    rcvbytes = string2bytes('')
    client_serving_socket, addr = server_socket.accept()
    client_serving_socket.settimeout(1)
  
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
        print('Daten, die wir an WR senden würden: \r\n' + getokmsg() + "\r\n")
        client_serving_socket.send(string2bytes(getokmsg()))
      elif rcvdatenstring.find('<re') >= 0: # Fehlermeldung empfangen
        print('Empfangene Nachricht enthält Fehlermeldung des Wechselrichters <re>\r\n')
        print('Daten, die wir an WR senden würden: \r\n' + getokmsg() + "\r\n")
        client_serving_socket.send(string2bytes(getokmsg()))
      elif rcvdatenstring.find('<crq') >= 0: # Steuerungsdaten empfangen # Wenn Steuerdaten empfangen, dann in Uhrzeit setzen
        # Dem WR aktuelle Uhrzeit schicken schicken
        print('Empfangene Nachricht enthält Steuerungsanfrage des Wechselrichters <crq>\r\n')
        print('Daten, die wir an WR senden würden: \r\n' + gettimemsg() + "\r\n")
        client_serving_socket.send(string2bytes(gettimemsg()))

      else: #Bei falschem Format nur Ausgeben
        print('Falsches Datenformat empfangen!\r\n')
        print(rcvdatenstring)
        logstring += 'Falsches Datenformat empfangen!\r\n' + rcvdatenstring[rcvdatenstring.find('xmlData'):] + '\r\n'
        # Dem WR eine OK Nachricht schicken
        client_serving_socket.send(string2bytes(getokmsg()))
        print('Daten, die wir an WR senden würden: \r\n' + getokmsg() + "\r\n")

      # Daten an Wechselrichter senden
      #print("Daten vom GreenSynergy Portal an Wechselrichter senden.")
      #logstring += "Daten vom GreenSynergy Portal an Wechselrichter senden."
      #client_serving_socket.send(reply)
    else: # 
      print("Andere Daten empfangen: " + rcvdatenstring + '\r\n')
      logstring += "Andere Daten empfangen: " + rcvdatenstring + '\r\n'

    # Verbindung schließen
    client_serving_socket.close()
    del client_serving_socket

    #Daten in Loggingfile schreiben
    f = open(loggingfile, 'a')
    f.write(logstring)
    f.close()
    logstring = ''

    # #Werte dekodieren und in csv schreiben
    # #Logfilepfad initialisieren
    # datalogfile = datalogpath + time.strftime("%Y_%m_") + datalogfilename
    # errlogfile = errlogpath + time.strftime("%Y_%m_") + errlogfilename
    # loggingfile = loggingpath + time.strftime("%Y_%m_") + loggingfilename
    # #Prüfe ob Störungen oder Daten empfangen wurden
    # if rcvdatenstring.find('<rd') >= 0:#Wenn Daten empfangen, dann in datalogfile schreiben

    #   try:#Prüfe ob Datei existiert
    #     f = open(datalogfile, 'r')
    #     #lastline = f.readlines()[-1]
    #     #print(lastline)
    #     f.close()
    #   except BaseException as e:#Wenn nicht dann neue Datei erstellen und Spaltenbeschriftung hinzufügen
    #     print(str(e) + '\r\n')
    #     logstring += str(e) + '\r\n' + 'Datalogfile existiert nicht ==> neues erstellen!' + '\r\n'
    #     initdatalogfile(datalogfile)
    #   csvdata = decodedata(rcvdatenstring)
    #   #Daten in File schreiben
    #   f = open(datalogfile, 'a')
    #   f.write(csvdata)
    #   f.close()
    #   #Dem WR eine OK Nachricht schicken
    #   client_serving_socket.send(string2bytes(getokmsg()))
      
    # elif rcvdatenstring.find('<re') >= 0:#Wenn Errordaten empfangen, dann in errlogfile schreiben

    #   try:#Prüfe ob Datei existiert
    #     f = open(errlogfile, 'r')
    #     #lastline = f.readlines()[-1]
    #     #print(lastline)
    #     f.close()
    #   except BaseException as e:#Wenn nicht dann neue Datei erstellen und Spaltenbeschriftung hinzufügen
    #     print(str(e) + '\r\n')
    #     logstring += str(e) + '\r\n' + 'Errorlogfile existiert nicht ==> neues erstellen!' + '\r\n'
    #     initerrlogfile(errlogfile)
    #   #Daten in File schreiben
    #   f = open(errlogfile, 'a')
    #   f.write(decodeerr(rcvdatenstring))
    #   f.close()
    #   #Dem WR eine OK Nachricht schicken
    #   client_serving_socket.send(string2bytes(getokmsg()))
      
    # elif rcvdatenstring.find('<crq>') >= 0:#Wenn Steuerdaten empfangen, dann in Uhrzeit setzen
    #   #Dem WR aktuelle Uhrzeit schicken schicken
    #   client_serving_socket.send(string2bytes(gettimemsg()))


    # else:#Bei falschem Format nur Ausgeben
    #   print('Falsches Datenformat empfangen!\r\n')
    #   print(rcvdatenstring)
    #   logstring += 'Falsches Datenformat empfangen!\r\n' + rcvdatenstring[rcvdatenstring.find('xmlData'):] + '\r\n'
    #   #Dem WR eine OK Nachricht schicken
    #   client_serving_socket.send(string2bytes(getokmsg()))

    # daten = 0

    # #Sende zu Datenbankserver, wenn nicht gewünscht, nächste Zeile mit "#" auskommentieren
    # for adress in rawdataserver:
    #   print('Sende Daten zu greensynergy (bytes)')
    #   logstring += 'Sende Daten zu greensynergy (bytes)' + '\r\n'
    #   daten = sendbytes2portal(adress, block)

    # print('Sende Antwort von greensynergy zum WR')
    # logstring += 'Sende Antwort von greensynergy zum WR' + '\r\n'
    # client_serving_socket.send(daten)
    
    # #Verbindung schließen
    # client_serving_socket.close()
    # del client_serving_socket
    # #Daten in Loggingfile schreiben
    # f = open(loggingfile, 'a')
    # f.write(logstring)
    # f.close()
    # logstring = ''


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
