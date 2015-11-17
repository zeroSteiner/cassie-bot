import logging

class CassieXMPPBotModule(object):
	def __init__(self):
		self.options = {}
		self.bot = None
		self.brain = None

	def init_bot(self, bot):
		self.bot = bot

	def init_brain(self, brain):
		self.brain = brain

	def config_parser(self, config):
		return self.options

	def has_command(self, command):
		return hasattr(self, 'cmd_' + command)

	def get_command_handler(self, command):
		return getattr(self, 'cmd_' + command)

	@property
	def commands(self):
		return map(lambda x: x[4:], filter(lambda x: x.startswith('cmd_'), dir(self)))

	@property
	def logger(self):
		module_name = self.__module__.split('.')[-1]
		return logging.getLogger('cassie.bot.xmpp.modules.' + module_name)
