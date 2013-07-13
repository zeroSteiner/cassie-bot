from mayhem.pyasm.assembler import Assembler
from mayhem.pyasm.exceptions import AssemblyError, AssemblySyntaxError

from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

"""
# Example config:
[mod_assembler]
handler_timeout: 300
"""

class Module(CassieXMPPBotModule):
	def init_bot(self, *args, **kwargs):
		CassieXMPPBotModule.init_bot(self, *args, **kwargs)
		self.bot.command_handler_set_permission('assembler', 'user')

	def cmd_assembler(self, args, jid, is_muc):
		parser = ArgumentParserLite('assemble', 'mayhem python x86 assembler')
		parser.add_argument('-s', '--single', dest = 'single', help = 'assemble a single line')
		parser.add_argument('-i', '--interactive', dest = 'interactive', action = 'store_true', help = 'start an interactive session')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()
		if results['single']:
			return self.assemble_line(results['single'])
		elif results['interactive']:
			if is_muc:
				handler_id = self.bot.custom_message_handler_add(jid.bare, self.callback_interactive_assembler, self.options['handler_timeout'])
			else:
				handler_id = self.bot.custom_message_handler_add(jid, self.callback_interactive_assembler, self.options['handler_timeout'])
			return ['An interactive session has been started', 'Type quit to end the session']
		return parser.format_help()

	def assemble_line(self, line):
		ass = Assembler({'newline':';', 'comment':'\x00'})
		try:
			ass.load(line)
		except AssemblySyntaxError as err:
			print 'SyntaxError: ' + err.msg
		except Exception as err:
			return 'An Error Occurred'
		output = []
		for inst in ass.instructions:
			output.append(repr(inst))
		return output

	def callback_interactive_assembler(self, msg, jid, handler_id):
		msg = msg.strip()
		if not msg:
			return
		if msg in ['quit', 'exit']:
			self.bot.custom_message_handler_del(handler_id = handler_id)
			return 'The interactive session has been ended'
		return self.assemble_line(msg)

	def config_parser(self, config):
		self.options['handler_timeout'] = config.getint('handler_timeout', 600)
