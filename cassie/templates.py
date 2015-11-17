import logging
import os

class CassieXMPPBotModule(object):
	def __init__(self):
		self.options = {}
		self.bot = None
		self.name = self.__class__.__module__.split('.')[-1]

	def init_bot(self, bot):
		self.bot = bot

	def update_options(self, options):
		self.options.update(options)

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
