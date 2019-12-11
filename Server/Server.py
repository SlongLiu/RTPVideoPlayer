import sys, socket, os
from ServerWorker import ServerWorker


class Server:	
	
	def main(self):
		try:
			SERVER_PORT = 9707 # int(sys.argv[1])
		except:
			print("[Usage: Server.py Server_port]\n")
		while True:
			rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			rtspSocket.bind(('', SERVER_PORT))
			rtspSocket.listen(5)        

			# Receive client info (address,port) through RTSP/TCP session
			clientInfo = {}
			clientInfo['rtspSocket'] = rtspSocket.accept()
			ServerWorker(clientInfo).run()		

if __name__ == "__main__":
	(Server()).main()


