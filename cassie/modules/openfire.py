from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

class Module(CassieXMPPBotModule):
	# http://www.igniterealtime.org/projects/openfire/plugins/userservice/readme.html
	def cmd_openfire_admin_command(bot, args):
		parser = ArgumentParserLite('openfire', 'manager users on openfire')
		parser.add_argument('-a', '--add', dest = 'add_user', default = None, help = 'username to add')
		parser.add_argument('-d', '--del', dest = 'del_user', default = None, help = 'username to delete')
		parser.add_argument('-p', '--pass', dest = 'password', default = None, help = 'password for the new user')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()
		response = ''
		if results['add_user']:
			pass
		return None
