
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

	def get_comand_handler(self, command):
		return getattr(self, 'cmd_' + command)
