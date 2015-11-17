import logging
import os

class CassieXMPPBotModule(object):
	permissions = {}
	def __init__(self, bot):
		self.options = {}
		self.bot = bot
		self.name = self.__class__.__module__.split('.')[-1]
		for command, level in self.permissions.items():
			if not command in self.commands:
				raise ValueError('can not set permission for non-existing command: ' + command)
			self.bot.command_handler_set_permission(command, level)

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
