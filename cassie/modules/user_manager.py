from cassie.bot import users
from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

class Module(CassieXMPPBotModule):
	def cmd_user(self, args, jid, is_muc):
		parser = ArgumentParserLite('user', 'add/delete/modify users')
		parser.add_argument('-a', '--add', dest='add user', action='store', default=None, help='add user')
		parser.add_argument('-d', '--del', dest='delete user', action='store', default=None, help='delete user')
		parser.add_argument('-l', '--lvl', dest='level', action='store', default='USER', help='permission level of user')
		parser.add_argument('-s', '--show', dest='show', action='store_true', default=False, help='show the user database')
		if not len(args):
			return parser.format_help()

		results = parser.parse_args(args)
		response = ''
		authorized_users = self.bot.authorized_users
		privilege_level = users.get_level_by_name(results['level'])
		if privilege_level is None:
			return 'Invalid privilege level'
		if results['add user']:
			if not results['add user'] in authorized_users:
				authorized_users[results['add user']] = users.User(results['add user'], privilege_level)
				response += 'Successfully Added User: ' + results['add user']
			else:
				response += 'Can Not Add Already Authorized User'
		if results['delete user']:
			if not results['delete user'] in authorized_users:
				response += 'Can Not Delete Non-Authorized User'
			else:
				del authorized_users[results['delete user']]
				response += 'Successfully Deleted User: ' + results['delete user']
		if results['show']:
			if not response:
				response += '\n'
			response += 'User Listing:\n'
			for user in authorized_users:
				response += user.type.upper() + ' ' + user.name + ' ' + user.level_name + '\n'
			response += '\n'
		if not response:
			return 'Missing Action'
		response += '\n'
		try:
			authorized_users.save()
		except Exception:
			self.logger.error('failed to save the user database', exc_info=True)
			response += 'Failed To Save User Database'
		return response
