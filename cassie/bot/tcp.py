import os
import logging
import SocketServer
from cassie.brain import Brain as CassieAimlBrain

class CassieSocketRequestHandler(SocketServer.BaseRequestHandler):
	def handle(self):
		try:
			while True:
				self.request.send(self.prompt)
				data = self.request.recv(1024)
				response = self.brain.respond(data, self.client_address[0])
				if response:
					self.request.send(response + '\n')
		except:
			pass
		
class CassieTCPBot(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
	def __init__(self, bindinfo, aimls_path, botmaster, prompt):
		__shutdown__ = False
		SocketServer.TCPServer.__init__(self, bindinfo, CassieSocketRequestHandler)
		self.logger = logging.getLogger('cassie.bot.tcp')
		self.brain = CassieAimlBrain(modules = None)
		self.brain.verbose(False)
		self.brain.setBotPredicate('name', 'Cassie')
		self.brain.setBotPredicate('botmaster', botmaster)
		self.aimls_path = aimls_path
		for root, dirs, files in os.walk(self.aimls_path):
			for name in files:
				if os.path.join(root, name).endswith('.aiml'):
					self.brain.learn(os.path.join(root, name))
		self.logger.info('bot has been successfully initialized')
		self.logger.info("the AIML kernel contains {:,} categories".format(self.brain.numCategories()))
		self.RequestHandlerClass.brain = self.brain
		self.RequestHandlerClass.prompt = prompt
