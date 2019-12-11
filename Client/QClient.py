# from tkinter import *
# import tkinter.messagebox
from PIL import Image
import socket
import threading
import sys
import traceback
import os
import time

import pyaudio
import wave
from struct import Struct
from math import floor

from ClientUI import Ui_MainWindow
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QMainWindow, QApplication, QGraphicsScene, QGraphicsPixmapItem
from PyQt5.QtCore import pyqtSlot

sys.path.append('../')
from RtpPacket.RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache\cache-"
CACHE_FILE_EXT = ".jpg"


class Client(QMainWindow, Ui_MainWindow):
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3

    # Initiation..
    def __init__(self, parent=None):
        super(Client, self).__init__(parent)
        self.setupUi(self)
        self.scene = QGraphicsScene()
        self.image = QPixmap()
        self.horizontalSlider.setEnabled(False)

        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        # self.connectToServer()

        self.frameNbr = 0 # 视频帧数
        self.audioFrameNbr = 0 # 音频帧数
        self.audioRate = 44100 # 音频频率
        self.beginSlide = False # 是否在拖动进度条
        self.speed = 1 # 当前倍速 1: x1.0; 2: x2.0
        self.commandNow = -1 #当前命令

        if not os.path.exists('cache'):
            os.mkdir('cache')

        # =========signal slot begin============
        self.setupButton.clicked.connect(self.setupMovie)
        self.playButton.clicked.connect(self.playMovie)
        self.pauseButton.clicked.connect(self.pauseMovie)
        self.teardownButton.clicked.connect(self.exitClient)
        self.horizontalSlider.sliderReleased.connect(self.reposition)
        self.horizontalSlider.valueChanged.connect(self.setNowTimePoint)
        self.horizontalSlider.sliderPressed.connect(self.pauseMovie)
        # self.speedButton.click.connect(self.pauseMovie)
        self.speedButton.clicked.connect(self.changeSpeed)
        self.connectButton.clicked.connect(self.connectToServer)
        self.refreshButton.clicked.connect(self.refreshList)
        self.listWidget.itemClicked.connect(self.itemChoose)
        # =========signal slot end============

    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
            # # 创建播放器
            # self.p = pyaudio.PyAudio()

    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)
        # Delete the cache image from video
        os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
        for i in range(10):
            try:
                filename = CACHE_FILE_NAME + str(self.sessionId) + '-' + str(i) + '.wav'
                os.remove(filename)
            except:
                continue
        # 关闭播放器
        self.p.terminate()

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.beginSlide = True
            self.sendRtspRequest(self.PAUSE)

    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            self.beginSlide = False
            # Create a new thread to listen for RTP packets
            threading.Thread(target=self.listenRtp).start()
            threading.Thread(target=self.listenAudioRtp).start()
            self.playEvent = threading.Event()
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)

    def refreshList(self):
        """Refresh the list"""
        self.openRtpPort()
        self.sendRtspRequest(7)
        threading.Thread(target=self.listenList).start()

    def listenList(self):
        """Listen for UDP LIST."""
        while True:
            try:
                data = self.rtpSocket.recv(1024*64)
                if data:
                    fileList = data.decode().split(';')
                    for afile in fileList:
                        self.listWidget.addItem(afile)
                    self.rtpSocket.shutdown(socket.SHUT_RDWR)
                    self.rtpSocket.close()
                    break
            except Exception as e:
                print(e, '>> listenList')

                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket
                if self.teardownAcked == 1:
                    self.rtpSocket.shutdown(socket.SHUT_RDWR)
                    self.rtpSocket.close()
                    break

    def reposition(self):
        """reposition  handler."""
        if self.state == self.READY:
            playPoint = self.horizontalSlider.value()
            print('playPoint:', playPoint)
            # self.pauseMovie()
            # time.sleep(0.2)
            self.sendRtspRequest(5)
            self.beginSlide = False
    
    def changeSpeed(self):
        self.speedButton.setEnabled(False)
        if self.speed == 1:
            self.speed = 2
        else:
            self.speed = 1
        self.speedButton.setText('Speed:X%d' % self.speed)
        self.sendRtspRequest(6)        

    def listenRtp(self):
        """Listen for RTP packets."""
        while True:
            try:
                data = self.rtpSocket.recv(1024*64)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)

                    currFrameNbr = rtpPacket.seqNum()
                    # print("Current Seq Num: " + str(currFrameNbr))

                    if currFrameNbr > self.frameNbr:  # Discard the late packet
                        self.frameNbr = currFrameNbr
                        self.updateMovie(self.writeFrame(
                            rtpPacket.getPayload()))
                        if not self.beginSlide:
                            self.horizontalSlider.setValue(currFrameNbr/24)
                            self.label_2.setText('%.2fs' % (currFrameNbr/24))
            except Exception as e:
                print(e, '>> listenRtp')

                # Stop listening upon requesting PAUSE or TEARDOWN
                if self.playEvent.isSet():
                    break

                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket
                if self.teardownAcked == 1:
                    self.rtpSocket.shutdown(socket.SHUT_RDWR)
                    self.rtpSocket.close()
                    break
    
    def listenAudioRtp(self):
        """Listen for Audio RTP packets."""
        while True:
            try:
                data = self.rtpAudioSocket.recv(1024*64)
                if data:
                    rtpAudioPacket = RtpPacket()
                    rtpAudioPacket.decode(data)

                    currAudioFrameNbr = rtpAudioPacket.seqNum()
                    # print("Current Audio Seq Num: " + str(currAudioFrameNbr))

                    if currAudioFrameNbr > self.audioFrameNbr:  # Discard the late packet
                        self.audioFrameNbr = currAudioFrameNbr
                        # self.playMusic(self.cacheMusic(rtpAudioPacket.getPayload()))
                        filename = self.cacheMusic(rtpAudioPacket.getPayload(), currAudioFrameNbr % 10)
                        if self.speed == 1:
                            threading.Thread(target=self.playMusic, args=(filename,)).start()
                        
            except Exception as e:
                print(e, '>> listenAudioRtp')

                # Stop listening upon requesting PAUSE or TEARDOWN
                if self.playEvent.isSet():
                    break

                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket
                if self.teardownAcked == 1:
                    self.rtpAudioSocket.shutdown(socket.SHUT_RDWR)
                    self.rtpAudioSocket.close()
                    break

    def playMusic(self, filename):
        # try:
        wf = wave.open(filename, 'rb')
        CHUNK = 1024
        # read data
        data = wf.readframes(CHUNK)
        # 创建播放器
        # p = pyaudio.PyAudio()
        # 获得语音文件的各个参数
        FORMAT = self.p.get_format_from_width(wf.getsampwidth())
        CHANNELS = wf.getnchannels()
        RATE = wf.getframerate()
        # print('FORMAT: {} \nCHANNELS: {} \nRATE: {}'.format(FORMAT, CHANNELS, RATE))
        # 打开音频流， output=True表示音频输出
        stream = self.p.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        frames_per_buffer=CHUNK,
                        output=True)
        # play stream (3) 按照1024的块读取音频数据到音频流，并播放
        while len(data) > 0:
            stream.write(data)
            data = wf.readframes(CHUNK)
        # # 停止数据流  
        # stream.stop_stream()
        # stream.close()
        # 关闭 PyAudio  
        # p.terminate()  

    def cacheMusic(self, data, num):
        """play wave bytes: data"""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + '-' + str(num) + '.wav'
        out = wave.open(cachename, 'wb')
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(self.audioRate)
        out.writeframes(data)
        out.close()
        
        return cachename

    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        file = open(cachename, "wb")
        file.write(data)
        file.close()

        return cachename

    def updateMovie(self, imageFile):
        """Update the image file as video frame in the GUI."""
        pixmap = QPixmap(imageFile)
        self.label.setPixmap(pixmap)
        self.label.setScaledContents(True)


    def connectToServer(self):
        """Connect to the Server. Start a new RTSP/TCP session."""

        self.serverAddr = self.serverAddrEdit.text() # serveraddr
        self.serverPort = int(self.serverPortEdit.text()) # int(serverport)
        self.rtpPort = int(self.videoPortEdit.text())
        self.rtpAudioPort = int(self.audioPortEdit.text())

        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
            self.label.setText('Connected Success! Please choose a file and push SETUP button')
        except:
            print('Connection Failed', 'Connection to \'%s\' failed.' % self.serverAddr)
            self.label.setText('Connected Failed, Please Try Again!')
        self.teardownAcked = 0
        self.refreshList()
        self.refreshButton.setEnabled(False)
        

    def sendRtspRequest(self, requestCode):
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            self.rtspSeq += 1

            request = "SETUP " + self.fileName + " RTSP/1.0"
            request += "\nCSeq: " + str(self.rtspSeq)
            request += "\nTransport: RTP/UDP; client_port= " + str(self.rtpPort)
            request += "\nTransport: RTP/UDP; client_port= " + str(self.rtpAudioPort)

            self.requestSent = self.SETUP
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1

            request = "PLAY " + self.fileName + " RTSP/1.0"
            request += "\nCSeq: " + str(self.rtspSeq)
            request += "\nSession: " + str(self.sessionId)

            self.requestSent = self.PLAY
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1

            request = "PAUSE " + self.fileName + " RTSP/1.0"
            request += "\nCSeq: " + str(self.rtspSeq)
            request += "\nSession: " + str(self.sessionId)

            self.requestSent = self.PAUSE
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1

            request = "TEARDOWN " + self.fileName + " RTSP/1.0"
            request += "\nCSeq: " + str(self.rtspSeq)
            request += "\nSession: " + str(self.sessionId)

            self.requestSent = self.TEARDOWN
        elif requestCode == 5: # reposition
            self.rtspSeq += 1
            self.frameNbr = 0

            request = "REPOSITION " + self.fileName + " RTSP/1.0"
            request += "\nCSeq: " + str(self.rtspSeq)
            request += "\nSession: " + str(self.sessionId)
            request += '\n' + str(self.horizontalSlider.value())

            self.requestSent = 5
        elif requestCode == 6: # changeSpeed
            self.rtspSeq += 1

            request = "CHANGESPEED " + self.fileName + " RTSP/1.0"
            request += "\nCSeq: " + str(self.rtspSeq)
            request += "\nSession: " + str(self.sessionId)
            request += '\nSpeed: ' + str(self.speed)

            self.requestSent = 6
        elif requestCode == 7: # Find the file list
            self.rtspSeq += 1

            request = "FILE " + "RTSP/1.0"
            request += "\nCSeq: " + str(self.rtspSeq)
            request += "\nTransport: RTP/UDP; client_port= " + str(self.rtpPort)    

            self.requestSent = 7
        else:
            print('requestCode=%d\tself.state=%d' % (requestCode, self.state))
            return
        self.rtspSocket.send(request.encode())
        print('\nData sent:\n' + request)

    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        while True:
            reply = self.rtspSocket.recv(1024)

            if reply:
                self.parseRtspReply(reply.decode("utf-8"))

            # Close the RTSP socket upon requesting Teardown
            if self.requestSent == self.TEARDOWN:
                self.rtspSocket.shutdown(socket.SHUT_RDWR)
                self.rtspSocket.close()
                break

    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        print(data)
        lines = data.split('\n')
        seqNum = int(lines[1].split(' ')[1])

        # Process only if the server reply's sequence number is the same as the request's
        if seqNum == self.rtspSeq:
            session = int(lines[2].split(' ')[1])
            # New RTSP session ID
            if self.sessionId == 0:
                self.sessionId = session

            # Process only if the session ID is the same or the file command
            if self.sessionId == session or session == -1:
                if int(lines[0].split(' ')[1]) == 200:
                    if self.requestSent == self.SETUP:
                        self.state = self.READY
                        self.movieDuartion = int(lines[-1])/1000/1000
                        self.label_3.setText(str(self.movieDuartion))
                        self.horizontalSlider.setMaximum(self.movieDuartion)
                        self.horizontalSlider.setEnabled(True)
                        # Open RTP port.
                        self.openRtpPort()
                        self.openAudioRtpPort()
                        # 创建播放器
                        self.p = pyaudio.PyAudio()
                        self.label.setText('SETUP Success! Please push PLAY button')
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY
                        self.playEvent.set()
                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT
                        # Flag the teardownAcked to close the socket.
                        self.teardownAcked = 1
                        self.label.setText('TEARDWON. Please push connect button')
                    elif self.requestSent == 5: # 已完成重定位
                        self.playMovie()
                    elif self.requestSent == 6:
                        self.speedButton.setEnabled(True)

    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        # Create a new datagram socket to receive RTP packets from the server
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Set the timeout value of the socket to 0.5sec
        self.rtpSocket.settimeout(0.5)

        try:
            # Bind the socket to the address using the RTP port given by the client user
            self.rtpSocket.bind(('', self.rtpPort))

        except:
            print(
                'Unable to Bind', 'Unable to bind PORT=%d' % self.rtpPort)

    def openAudioRtpPort(self):
        self.rtpAudioSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpAudioSocket.settimeout(0.5)
        # try:
        self.rtpAudioSocket.bind(('', self.rtpAudioPort))
    
    def setNowTimePoint(self, time):
        if self.beginSlide:
            self.label_2.setText('%.2fs' % time)

    def setBeginSlide(self):
        self.beginSlide = True

    def itemChoose(self, item):
        self.fileName = item.text()
        self.label.setText('%s choosen! Please push SETUP button' % item.text())




if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    # ui = Ui_MainWindow()

    client = Client()

    client.show()
    sys.exit(app.exec_())    