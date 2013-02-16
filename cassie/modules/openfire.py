from cassie.argparselite import ArgumentParserLite

# http://www.igniterealtime.org/projects/openfire/plugins/userservice/readme.html
def openfire_admin_command(bot, args):
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

def config_parser(config):
	opts = {}
	return opts

def init_bot(bot, opts):
	bot.add_command(openfire_admin_command, 'openfire')
