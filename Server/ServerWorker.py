from random import randint
import sys, traceback, threading, socket, os
import time
import multiprocessing

# from VideoStream import VideoStream
from Mp4Stream import Mp4Stream
sys.path.append('../')
from RtpPacket.RtpPacket import RtpPacket

class ServerWorker(multiprocessing.Process):
	SETUP = 'SETUP'
	PLAY = 'PLAY'
	PAUSE = 'PAUSE'
	TEARDOWN = 'TEARDOWN'
	
	INIT = 0
	READY = 1
	PLAYING = 2
	state = INIT

	OK_200 = 0
	FILE_NOT_FOUND_404 = 1
	CON_ERR_500 = 2
	
	clientInfo = {}
	
	def __init__(self, clientInfo):
		multiprocessing.Process.__init__(self)
		self.clientInfo = clientInfo
		self.playTime = (0.0, time.time())
		self.audioPlayTime = (0.0, time.time())
		self.speed = 1
		
	def run(self):
		threading.Thread(target=self.recvRtspRequest).start()
	
	def recvRtspRequest(self):
		"""Receive RTSP request from the client."""
		connSocket = self.clientInfo['rtspSocket'][0]
		while True:            
			data = connSocket.recv(256)
			if data:
				print("====Data received====\n" + data.decode("utf-8") + '\n')
				if self.processRtspRequest(data.decode("utf-8"))=='TEARDOWN':
					print('Teardown the movie')
					break
	
	def processRtspRequest(self, data):
		"""Process RTSP request sent from the client."""
		# Get the request type
		request = data.split('\n')
		line1 = request[0].split(' ')
		requestType = line1[0]
		self.requestType = requestType
		
		# Get the media file name
		filename = line1[1]
		
		# Get the RTSP sequence number 
		seq = request[1].split(' ')
		
		# Process SETUP request
		if requestType == self.SETUP:
			if self.state == self.INIT:
				# Update state
				print("processing SETUP\n")
				
				try:
					self.clientInfo['videoStream'] = Mp4Stream(os.path.join('video', filename))
					self.clientInfo['audioStream'] = Mp4Stream(os.path.join('video', filename))
					self.state = self.READY
				except IOError as e:
					print(e)
					self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
				
				# Generate a randomized RTSP session ID
				self.clientInfo['session'] = randint(100000, 999999)
				
				# Send RTSP reply
				self.replyRtsp(self.OK_200, seq[1])
				
				# Get the RTP/UDP port from the last line
				self.clientInfo['rtpPort'] = request[2].split(' ')[3]
				self.clientInfo['rtpAudioPort'] = request[3].split(' ')[3]

		
		# Process PLAY request 		
		elif requestType == self.PLAY:
			if self.state == self.READY:
				print("processing PLAY\n")
				self.state = self.PLAYING
				
				# Create a new socket for RTP/UDP
				self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				self.clientInfo["rtpAudioSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
				
				self.replyRtsp(self.OK_200, seq[1])
				
				# The pic time
				self.playTime = (max(0.0, self.playTime[0]), time.time())
				self.audioPlayTime = (max(0.0, self.audioPlayTime[0]), time.time())

				# Create a new thread and start sending RTP packets
				self.clientInfo['event'] = threading.Event()

				self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
				self.clientInfo['worker'].start()

				self.clientInfo['audioWorker']= threading.Thread(target=self.sendAudioRtp) 
				self.clientInfo['audioWorker'].start()
			else:
				print(self.state, 'skip PLAY\n')
		
		# Process PAUSE request
		elif requestType == self.PAUSE:
			if self.state == self.PLAYING:
				print("processing PAUSE\n")
				self.state = self.READY
				
				self.clientInfo['event'].set()
			
				self.replyRtsp(self.OK_200, seq[1])
		
		# Process TEARDOWN request
		elif requestType == self.TEARDOWN:
			print("processing TEARDOWN\n")

			self.clientInfo['event'].set()
			
			self.replyRtsp(self.OK_200, seq[1])
			
			# Close the RTP socket
			self.clientInfo['rtpSocket'].close()
			self.clientInfo['rtpAudioSocket'].close()
		
		# Process REPOSITION request
		elif requestType == 'REPOSITION':
			print("processing REPOSITION\n")
			# 1. Reopen
			try:
				# self.clientInfo['videoStream'] = VideoStream(filename)
				self.clientInfo['videoStream'] = Mp4Stream(os.path.join('video', filename))
				self.clientInfo['audioStream'] = Mp4Stream(os.path.join('video', filename))
			except IOError as e:
				print(e)
				self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])

			# 2. find the proper frame
			timeNeed = int(request[3].strip())
			# The pic time
				
			data = self.clientInfo['videoStream'].nextFrame()
			while(self.clientInfo['videoStream'].frameTime() < timeNeed):
				data = self.clientInfo['videoStream'].nextFrame()
				# print('time:', self.clientInfo['videoStream'].frameTime())
			audioData = self.clientInfo['audioStream'].nextAudioFrame()
			while(self.clientInfo['audioStream'].get_audioFrameTime() < timeNeed):
				audioData = self.clientInfo['audioStream'].nextAudioFrame()
			print('######## Finished position to new time ########\n')

			self.replyRtsp(self.OK_200, seq[1])
				
			self.playTime = (timeNeed, time.time())
			self.audioPlayTime = (timeNeed, time.time())

		# Process CHANGESPEED request
		elif requestType == 'CHANGESPEED':
			self.speed = int(request[3].split(' ')[1].strip())
			self.replyRtsp(self.OK_200, seq[1])
		
		elif requestType == 'FILE' :
			res = ''
			for afile in os.listdir('video/'):
				if afile[-3:] == 'mp4':
					res = res + ';' + afile
			if res!='':
				res = res[1:]
			else:
				res = '-'
			print(res+'\n')

			address = self.clientInfo['rtspSocket'][1][0]
			port = int(request[2].split(' ')[-1])
			self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			self.clientInfo["rtpSocket"].sendto(res.encode(),(address,port))
			self.clientInfo["rtpSocket"].close()

			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq[1] + '\nSession: ' + '-1'
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
			print(reply)

		return requestType
			
	def sendRtp(self):
		"""Send RTP packets over UDP."""
		while True:
			# self.clientInfo['event'].wait(0.01) 
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet(): 
				break 
				
			data = self.clientInfo['videoStream'].nextFrame()
			# data = self.clientInfo['videoStream'].nextFrame()
			if data: 
				frameNumber = self.clientInfo['videoStream'].frameNbr()
				frameTime = self.clientInfo['videoStream'].frameTime( )
				sleepTime = max(0.0, ((frameTime - self.playTime[0])*(1/self.speed) - (time.time() - self.playTime[1])))
				# print("#Video# %d:\t%f" % (frameNumber, sleepTime), frameTime, self.playTime)
				time.sleep(sleepTime)
				try:
					address = self.clientInfo['rtspSocket'][1][0]
					port = int(self.clientInfo['rtpPort'])
					self.clientInfo['rtpSocket'].sendto(self.makeRtp(data, frameNumber),(address,port))
					self.playTime = (frameTime, time.time())
				except Exception as e:
					print(e)
					print("sendRtp Error")
					#print('-'*60)
					#traceback.print_exc(file=sys.stdout)
					#print('-'*60)
			else:
				print("No data")
				break 

	def sendAudioRtp(self):
		"""Send audio RTP over UDP"""
		while True:
			
			# Stop sending if request is PAUSE or TEARDOWN
			if self.clientInfo['event'].isSet(): 
				break 
				
			data = self.clientInfo['audioStream'].nextAudioFrame()

			if data: 
				audioFrameNumber = self.clientInfo['audioStream'].audioFrameNbr()
				audioFrameTime = self.clientInfo['audioStream'].get_audioFrameTime()
				sleepTime = max(0.0, (audioFrameTime - self.audioPlayTime[0])*(1/self.speed) - (time.time() - self.audioPlayTime[1]))
				# print("$Audio$ %d:\t%f" % (audioFrameNumber, sleepTime), audioFrameTime, self.audioPlayTime)
				time.sleep(sleepTime)
				try:
					address = self.clientInfo['rtspSocket'][1][0]
					port = int(self.clientInfo['rtpAudioPort'])
					self.clientInfo['rtpAudioSocket'].sendto(self.makeRtp(data, audioFrameNumber),(address,port))
					self.audioPlayTime = (audioFrameTime, time.time())
				except Exception as e:
					print("sendAudioRtp Error:")
					print(e)
					#print('-'*60)
					#traceback.print_exc(file=sys.stdout)
					#print('-'*60)
			else:
				print("No Audio data")
				break

	def makeRtp(self, payload, frameNbr):
		"""RTP-packetize the video data."""
		version = 2
		padding = 0
		extension = 0
		cc = 0
		marker = 0
		pt = 26 # MJPEG type
		seqnum = frameNbr
		ssrc = 0 
		
		rtpPacket = RtpPacket()
		
		rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
		
		return rtpPacket.getPacket()
		
	def replyRtsp(self, code, seq):
		"""Send RTSP reply to the client."""
		if code == self.OK_200:
			#print("200 OK")
			reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
			if self.requestType == 'SETUP':
				reply = reply + '\n' + str(self.clientInfo['videoStream'].get_duration())
			connSocket = self.clientInfo['rtspSocket'][0]
			connSocket.send(reply.encode())
			print(reply)
		
		# Error messages
		elif code == self.FILE_NOT_FOUND_404:
			print("404 NOT FOUND")
		elif code == self.CON_ERR_500:
			print("500 CONNECTION ERROR")
