#!/usr/bin/env python
"""
Copyright (c) 2008, Benjie Gillam
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
    * Neither the name of MythPyWii nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
# By Benjie Gillam http://www.benjiegillam.com/mythpywii/
"""
# modified by loomy

Changelog:
 Whole script runs in an endless loop now
  -added a hook for a mythfrontend restart script if frontend crashes an socket is gone
  -added "mplayer-mode"
	 press "B" and "2" on wiimote to get in mplayer mode
	  mplayer has to be startet with "-input file=/tmp/mplayer" to read commands from fifo
	 buttons in mplayer mode:
	 	"B" and "2" 	: to return in normal mode
		"HOME" 		: close mplayer
		"UP","DOWN" 	: Seek
		"+" 		: Pause
		"-" 		: load a playlist (change location here in the script)
		"B" and "LEFT","RIGHT" : adjust Volume
 -added vlc mode to read a playlist from IPTV for example.(change in script)
 -added wminput-mode
 	2 different modes. one mode usses wiimote acceleration to move mouse pointer.
	the other mode uses the wiimote pointer. just put two candles in front of your tv to use it.

	"B" and "-" after disconnect quickly press  "1" and "2" to connect to wminput
		pointing mode. point your mouse cursor
	"B" and "+" after disconnect quickly press  "1" and "2" to connect to wminput
		acceleration mode. spin the wiimote to move the cursor
	"B" is mouse click in both modes

	after dissconneting the wiimote(OFF button), you can reconnect to this script in normal mode

 -added battery level indication
 	LED_1+4 = max
	LED_1+3 = med
	LED_1+2 = low
	LED_1 = nearly empty
	change the values at the bottom if not working right. depends on your battery
 -added proctitle support
	writes status information in process list to be checked by other processes
	cpufreqd for example
 -added an idlettime checker
	autmatically disconnects the wiimote after 20 minutes without a key press
	warns you before disconnecting with led status: LED_2 + LED_4 


check for Errors on stdout
 
"""

import cwiid, time, StringIO, sys, asyncore, socket
from math import log, floor, atan, sqrt, cos, exp

import os 
import sys
import setproctitle
# Note to self - list of good documentation:
# cwiid: http://flx.proyectoanonimo.com/proyectos/cwiid/
# myth telnet: http://www.mythtv.org/wiki/index.php/Telnet_socket


def do_scale(input, max, divisor=None):
	if divisor is None: divisor = max
	if (input > 1): input = 1
	if (input < -1): input = -1
	input = int(input * divisor)
	if input>max: input = max
	elif input < -max: input = -max
	return input


class MythSocket(asyncore.dispatcher):
	firstData = True
	data = ""
	prompt="\n# "
	owner = None
	buffer = ""
	callbacks = []
	oktosend = True
	def __init__(self, owner):
		self.owner = owner
		asyncore.dispatcher.__init__(self)
		self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
		
		self.connect(("localhost", 6546))
	def handle_connect(self):
	  pass
		#print "Connected"
	def handle_close(self):
		print "Mythfrontend connection closed"
		self.owner.socket_disconnect()
		self.close()
	def handle_read(self):
		try:
			self.data = self.data + self.recv(8192)
		except:
			pid = os.fork()
			if pid == 0:
				os.execl('/home/loomy/bin/mythstart', 'mythstart')
		        else:		
				sleep(2)
				print """
	[ERROR] The connection to Mythfrontend failed - trying to start it...
	"""
				#self.handle_close()
				return
		while len(self.data)>0:
			a = self.data.find(self.prompt)
			if a>-1:
				self.oktosend = True
				result = self.data[:a]
				self.data = self.data[a+len(self.prompt):]
				if not self.firstData:
					print ">>>", result
					cb = self.callbacks.pop(0)
					if cb:
						cb(result)
				else:
					print "Logged in to MythFrontend"
					self.firstData = False
			else:
				break;
	def writable(self):
		return (self.oktosend) and (len(self.buffer) > 0) and (self.buffer.find("\n") > 0)
	def handle_write(self):
		a = self.buffer.find("\n")
		sent = self.send(self.buffer[:a+1])
		print "<<<", self.buffer[:sent-1]
		self.buffer = self.buffer[sent:]
		self.oktosend = False
	def cmd(self, data, cb = None):
		self.buffer += data + "\n"
		self.callbacks.append(cb)
	def raw(self, data):
		cmds = data.split("\n")
		for cmd in cmds:
			if len(cmd.strip())>0:
				self.cmd(cmd)
	def ok(self):
		return len(self.callbacks) == len(self.buffer) == 0


class WiiMyth:
	wii_calibration = False
	wm = None
	ms = None
	wii_calibration = None
	#Initialize variables
	reportvals = {"accel":cwiid.RPT_ACC, "button":cwiid.RPT_BTN, "ext":cwiid.RPT_EXT, "status":cwiid.RPT_STATUS}
	report={"accel":True, "button":True}
	state = {"acc":[0, 0, 1]}
	lasttime = 0.0
	laststate = {}
	responsiveness = 0.15
	firstPress = True
	firstPressDelay = 0.5
	maxButtons = 0
	mplayer = 0
	dpms = 0
	lastled = cwiid.LED1_ON | cwiid.LED4_ON
	mplayerspeed=0
	mfifo = 0
	idle = 0
	maxspeed=0
	def fifowrite(self, msg):
		try:
			self.mfifo = open('/tmp/mplayer','w+')
			self.mfifo.write(msg)
			self.mfifo.close()
			return
		except:
			print "except in fifowrite"
			return
	#wii_rel = lambda v, axis: float(v - self.wii_calibration[0][axis]) / (
	#	self.wii_calibration[1][axis] - self.wii_calibration[0][axis])
	def wii_rel(self, v, axis):
		return float(v - self.wii_calibration[0][axis]) / (
		self.wii_calibration[1][axis] - self.wii_calibration[0][axis])
	def socket_quietdisconnect(self):
		if self.wm is not None:
			self.wm.led = cwiid.LED2_ON | cwiid.LED3_ON
			self.wm.close()
			#self.wm = None
		return
	def socket_disconnect(self):
		if self.wm is not None:
			for a in range(8):
				self.wm.rumble=1
				time.sleep(.2)
				self.wm.rumble=0
				time.sleep(.2)
			self.wm.led = cwiid.LED2_ON | cwiid.LED3_ON
			self.wm.close()
			self.wm = None
		return
	def wmconnect(self):
		print "Please open Mythfrontend and then press 1&2 on the wiimote..."
		try:
			self.wm = cwiid.Wiimote()
		except:
			self.wm = None
			if self.ms is not None:
				self.ms.close()
				self.ms = None
			return None
		self.ms = MythSocket(self)
		print "Connected to a wiimote :)"
		setproctitle.setproctitle('mythwiicontrol_connected')
		self.wm.rumble=1
		time.sleep(.2)
		self.wm.rumble=0
		# Wiimote calibration data (cache this)
		self.wii_calibration = self.wm.get_acc_cal(cwiid.EXT_NONE)
		return self.wm
	def wmdisconnect(self):
		print "disconnecting...."
		#self.wm = cwiid.Wiimote_close(self.wm)
		self.wm = cwiid.close(self.wm)
		self.wm.close()
		self.wm = None
		self.handle.close()
		return self.wm
	def wmcb(self, messages, bla):
		state = self.state
		for message in messages:
			if message[0] == cwiid.MESG_BTN:
				state["buttons"] = message[1]
			elif message[0] == cwiid.MESG_STATUS:
				print "\nStatus: ", message[1]
			elif message[0] == cwiid.MESG_ERROR:
				if message[1] == cwiid.ERROR_DISCONNECT:
					self.wm = None
					if self.ms is not None:
						self.ms.close()
						self.ms = None
					continue
				else:
					print "ERROR: ", message[1], "battery empty? ...will disconnect now"
					self.wm.close()
					self.wm = None

			elif message[0] == cwiid.MESG_ACC:
				state["acc"] = message[1]
			else:
				print "Unknown message!", message
			laststate = self.laststate
			#print "wmcb() ", state ,"und", laststate
			#self.idle += 1
			#print "B: %d/%d %d          \r" % (state["buttons"],self.maxButtons,self.ms.ok()),
			#sys.stdout.flush()
			if ('buttons' in laststate) and (laststate['buttons'] <> state['buttons']):
				self.idle = 0
				if self.lastled == cwiid.LED2_ON | cwiid.LED4_ON:
					self.wm.led = cwiid.LED1_ON | cwiid.LED4_ON
					self.lastled = cwiid.LED1_ON | cwiid.LED4_ON
				if state['buttons'] == 0:
					self.maxButtons = 0
				elif state['buttons'] < self.maxButtons:
					continue
				else:
					self.maxButtons = state['buttons']
				self.lasttime = 0
				self.firstPress = True
				if laststate['buttons'] == cwiid.BTN_B and not state['buttons'] == cwiid.BTN_B:
					#del state['BTN_B']
					if not (state['buttons'] & cwiid.BTN_B):
						self.ms.cmd('play speed normal')
						self.maxspeed = 0
				#if (laststate['buttons'] & cwiid.BTN_A and laststate['buttons'] & cwiid.BTN_B) and not (state['buttons'] & cwiid.BTN_A and state['buttons'] & cwiid.BTN_B):
					#self.ms.cmd('play speed normal')
				#	continue
			else:
				self.idle += 1
				#7600 sind ca. 2min
				idletime=250000
				if self.idle == idletime-15000:
					self.wm.led = cwiid.LED2_ON | cwiid.LED4_ON
					self.lastled = cwiid.LED2_ON | cwiid.LED4_ON
				if self.idle == idletime:	
					self.socket_quietdisconnect()
					self.wm = None
			if self.ms.ok() and (self.wm is not None) and (state["buttons"] > 0) and (time.time() > self.lasttime+self.responsiveness):
				self.lasttime = time.time()
				wasFirstPress = False
				if self.firstPress:
					wasFirstPress = True
					self.lasttime = self.lasttime + self.firstPressDelay
					self.firstPress = False
				# Stuff that doesn't need roll/etc calculations
				if state["buttons"] == cwiid.BTN_HOME:
					if self.mplayer == 1:
						self.fifowrite('quit\n')
					else:	
						self.ms.cmd('key escape')
				if state["buttons"] == cwiid.BTN_A:
					self.ms.cmd('key enter')
				#if state["buttons"] == cwiid.BTN_MINUS:
				#	self.ms.cmd('key z')
				if state["buttons"] == cwiid.BTN_UP:
					if self.mplayer == 1:
						self.fifowrite('Seek 20\n')
					else:	
						self.ms.cmd('key up')
				if state["buttons"] == cwiid.BTN_DOWN:
					if self.mplayer == 1:
						self.fifowrite('Seek -20\n')
					else:	
						self.ms.cmd('key down')
				if state["buttons"] == cwiid.BTN_LEFT:
					self.ms.cmd('key left')
				if state["buttons"] == cwiid.BTN_RIGHT:
					self.ms.cmd('key right')
				if state["buttons"] == cwiid.BTN_PLUS:
					self.ms.cmd('key p')
					self.fifowrite("Pause\n")
				if state["buttons"] == cwiid.BTN_MINUS:
					if self.mplayer == 1:
						self.fifowrite('loadlist /mnt/extern/movies/1stream.mru\n')
					else:	
						self.ms.cmd('key z')
				if state["buttons"] == cwiid.BTN_1:
					self.ms.cmd('key d')
				if state["buttons"] == cwiid.BTN_2:
					self.ms.cmd('key m')
				# Do we need to calculate roll, etc?
				# Currently only BTN_B needs this.
				##calcAcc = state["buttons"] & cwiid.BTN_B
				##calcAcc = 0
				##if calcAcc:
					# Calculate the roll/etc.
				##	X = self.wii_rel(state["acc"][cwiid.X], cwiid.X)
				##	Y = self.wii_rel(state["acc"][cwiid.Y], cwiid.Y)
				##	Z = self.wii_rel(state["acc"][cwiid.Z], cwiid.Z)
				##	if (Z==0): Z=0.00000001 # Hackishly prevents divide by zeros
				##	roll = atan(X/Z)
				##	if (Z <= 0.0):
				##		if (X>0): roll += 3.14159
				##		else: roll -= 3.14159
				##	pitch = atan(Y/Z*cos(roll))
					#print "X: %f, Y: %f, Z: %f; R: %f, P: %f; B: %d    \r" % (X, Y, Z, roll, pitch, state["buttons"]),
					sys.stdout.flush()
				#WII pointer in IR Mode	
				if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_MINUS:
					self.socket_quietdisconnect()
					os.system('wminput')
					self.wm = None
					return
				#WII pointer in "neigungs" Mode	
				if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_PLUS:
					self.socket_quietdisconnect()
					os.system('wminput -c /etc/cwiid/wminput/default_accel')
					self.wm = None
					return
				if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_LEFT:
					if self.mplayer == 1:
						self.fifowrite("Volume -50 0\n")
					else:	
						self.ms.cmd('key f10')
				if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_RIGHT:
					if self.mplayer == 1:
						self.fifowrite("Volume +50 0\n")
					else:	
						self.ms.cmd('key f11')
				if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_DOWN:
					self.ms.cmd('key h')
				#if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_UP:
				#	self.ms.cmd('key q')
				if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_1:
					print "starting vlc player.."
					pid = os.fork()
					if pid == 0:
						os.execl('/usr/bin/vlc', 'mythvlc', '--fullscreen', '--play-and-exit', '/home/loomy/alice.http.m3u' )
					#else:		
				if state["buttons"] & cwiid.BTN_B and state["buttons"] & cwiid.BTN_2:
					print "jepp. mplayer=",self.mplayer
					#os.system("/home/loomy/bin/ifstartwminput &")
					if self.mplayer == 0:
						self.mplayer = 1
						self.wm.led = cwiid.LED2_ON | cwiid.LED3_ON
						#self.ms.cmd('key p')
					else:
						self.mplayer = 0
						self.wm.led = self.lastled 
					#if cmd is not None:
					#	self.ms.raw(cmd)
					#	if self.mplayer == 10:
					#		mcmd ='echo "seek ',mplayerspeed
					#		mcmd += '\n'
					#		print mcmd
					#		self.fifowrite(mcmd)
			self.laststate = state.copy() #NOTE TO SELF: REMEMBER .copy() !!!
	def mythLocation(self, data):
		#Playback Recorded 00:00:49 of 00:25:31 1x 30210 2008-09-10T09:18:00 1243 /video/30210_20080910091800.mpg 25
		#PlaybackBox
		temp = data.split(" ")
		output = {}
		output['mode'] = temp[0]
		if output['mode'] == "Playback":
			output['position'] = temp[2]
			output['max'] = temp[4]
		return output
	def main(self):
		setproctitle.setproctitle('mythwiicontrol_starting')
		while True:
			if self.wm is None:
				#Connect wiimote
				self.wmconnect()
				if self.wm:
					#Tell Wiimote to display rock sign and check battery
					# 208 = CWIID_BATTERY_MAX
					#batt = self.wm.state["battery"] * 100 / 208
					batt = self.wm.state["battery"]
					print "batt=",batt 
					if batt < 150:	
						self.lastled = cwiid.LED1_ON 
					elif batt < 180:
						self.lastled = cwiid.LED1_ON | cwiid.LED2_ON
 					elif batt < 190:
						self.lastled = cwiid.LED1_ON | cwiid.LED3_ON
					else:
						self.lastled = cwiid.LED1_ON | cwiid.LED4_ON
					self.wm.led = self.lastled 	
					self.wm.rpt_mode = sum(self.reportvals[a] for a in self.report if self.report[a])
					self.wm.enable(cwiid.FLAG_MESG_IFC | cwiid.FLAG_REPEAT_BTN)
					self.wm.mesg_callback = self.wmcb
				else:
					process = os.popen('DISPLAY=":0" xset -q')
					output = process.read()
					process.close()
					if 'Monitor is in Suspend' in output:
						setproctitle.setproctitle('mythwiicontrol_idle')
						time.sleep(5);
					else:
						setproctitle.setproctitle('mythwiicontrol_searching')
					print "Retrying................ "
					print
			asyncore.loop(timeout=0, count=1)
			time.sleep(0.05)
			#self.wmdisconnect()	
		print "Exited Safely"

# Instantiate our class, and start.
inst = WiiMyth()
inst.main()
