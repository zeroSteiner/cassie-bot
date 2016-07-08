import datetime

from urllib.parse import urlparse

from cassie.argparselite import ArgumentParserLite
from cassie.imcontent import IMContentMarkdown
from cassie.templates import CassieXMPPBotModule

import requests

class EmpireAPI(object):
	"""Class to provide access to various functionality exposed through the Empire API"""

	def __init__(self, empire_config):
		"""Initialize a new instance of the EmpireAPI class"""
		self.username = empire_config['user']
		self.password = empire_config['pass']
		self.api_base_url = empire_config['url'] + 'api/'
		self.json_request_headers = {'Content-Type':'application/json'}
		self.verify_server_cert = False
		self._token = self._get_api_token()

	def _get_api_token(self):
	    """Get the token for the Empire server"""
	    server_url = self.api_base_url + 'admin/login'
	    creds = {"username": self.username, "password": self.password}
	    response = self.send_post_request(server_url, json=creds)
	    token = response['token']
	    return token

	def send_get_request(self, url):
		"""Send a GET request to the Empire server API"""
		response = requests.get(url, headers=self.json_request_headers, verify=self.verify_server_cert)
		return response.json()

	def send_post_request(self, url, json):
		"""Send a POST request to the Empire server API """
		response = requests.post(url, headers=self.json_request_headers, json=json, verify=self.verify_server_cert)
		return response.json()

	def get_api_token(self):
	    """Get the token for the Empire server"""
	    server_url = self.api_base_url + 'admin/login'
	    creds = {"username": self.username, "password": self.password}
	    response = self.send_post_request(server_url, json=creds)
	    return response['token']

	def get_listeners(self):
	    """Get the details of current listeners on the server"""
	    server_url = self.api_base_url + 'listeners?token={0}'.format(self._token)
	    response = self.send_get_request(server_url)
	    return response

	def get_agents(self):
	    """Get the details of current agents on the server"""
	    server_url = self.api_base_url + 'agents?token={0}'.format(self._token)
	    response = self.send_get_request(server_url)
	    return response

	def exec_shell_cmd(self, agent, cmd):
		"""Execute specified command on the specified agent"""
		server_url = self.api_base_url + 'agents/' + agent + '/shell?token={0}'.format(self._token)
		params = {"command":cmd}
		response = self.send_post_request(server_url, json=params)
		return response

	def get_cmd_output(self, agent):
		"""Get the results of previously executed command"""
		server_url = self.api_base_url + 'agents/' + agent + '/results?token={0}'.format(self._token)
		response = self.send_get_request(server_url)
		return response

	def get_creds(self):
		"""Get credentials from the database"""
		server_url = self.api_base_url + 'creds?token={0}'.format(self._token)
		response = self.send_get_request(server_url)
		return response

class Module(CassieXMPPBotModule):
	permissions = {'empire_list': 'user', 'empire_shell_exec': 'user', 'empire_setup': 'user'}
	
	def __init__(self, *args, **kwargs):
		super(Module, self).__init__(*args, **kwargs)
		self.report_rooms = []
		self.check_frequency = datetime.timedelta(0, 18)  # in seconds
		self.job_id = None
		self.job_start_time = datetime.datetime.utcnow()
		self.job_id = self.bot.job_manager.job_add(self._empire_poll, seconds=self.check_frequency.seconds)

	def update_options(self, config):
		if 'room' in config:
			self.report_rooms.append(config['room'])
		return self.options

	def get_authorized_users(self):
		"""Gets a list of users authorized for the application"""
		authorized_users = self.bot.authorized_users
		return authorized_users

	def get_storage(self, user_jid):
		"""Makes the Empire storage object available"""
		storage = self.bot.authorized_users[user_jid].storage.get('empire', {})
		self.bot.authorized_users[user_jid].storage['empire'] = storage
		return storage

	def user_is_configured(self, user_jid):
		"""Check that the user has a valid Empire config"""
		storage = self.get_storage(user_jid)
		config = True
		user = storage.get('user')
		passwd = storage.get('pass')
		url = storage.get('url')
		for x in [user, passwd, url]:
			if x is None:
				config = False
		return config

	def polling_is_enabled(self, user_jid):
		"""Check if the user enabled their server"""
		storage = self.get_storage(user_jid)
		return storage.get('is_enabled', True)

	def url_is_valid(self, url):
		"""Check if a URL is valid"""
		parsed_url = urlparse(url)
		return bool(parsed_url.scheme) and bool(parsed_url.netloc) and bool(parsed_url.path)

	def cmd_empire_setup(self, args, jid, is_muc):
		"""Create the Empire config file required by this module"""
		parser = ArgumentParserLite('empire_setup', 'Create an Empire config.')
		parser.add_argument('-s', '--server-url', dest='server_url', help='URL of Empire server (i.e. "https://127.0.0.1:1337/")', required=False)
		parser.add_argument('-u', '--username', dest='server_user', help='username for Empire API', required=False)
		parser.add_argument('-p', '--password', dest='server_pass', help='password for Empire API', required=False)
		parser.add_argument('-e', '--enable', dest='enable_server', help='enable automatic polling for your server', action='store_true', required=False, default=False)
		parser.add_argument('-d', '--disable', dest='disable_server', help='disable automatic polling for your server', action='store_true', required=False, default=False)
		parser.add_argument('-c', '--show-config', dest='show_config', help='displays your current Empire config', action='store_true', required=False, default=False)

		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		user_jid = str(jid).split('/')[0]
		user_storage = self.get_storage(user_jid)
		report_user = str(jid).split('@')[0]
		report = ''
		
		if results['enable_server'] and results['disable_server']:
			report = 'Automated polling cannot be both enabled and disabled.'
			return report

		if not self.polling_is_enabled(user_jid):
			user_storage['is_enabled'] = False

		if not self.user_is_configured and not all(results['server_user'], results['server_pass'], results['server_url']):
			report = "{0}: Your Empire config was not able to be updated successfully.\n".format(user_jid)
			report += 'You will not be able to leverage any Empire commands until your config is valid!\n'
			report += 'Please run the "!empire_setup" command again.'
			return report
		
		if results['enable_server'] and not self.polling_is_enabled(user_jid):
			user_storage['is_enabled'] = True
			report += '  Automatic polling has been enabled for your server.\n'
		
		if results['disable_server'] and self.polling_is_enabled(user_jid):
			user_storage['is_enabled'] = False
			user_storage['agents'] = []
			report += '  Automatic polling has been disabled for your server.\n'

		if results['server_user'] is not None:
			user_storage['user'] = results['server_user']

		if results['server_pass'] is not None:
			user_storage['pass'] = results['server_pass']
		
		if results['server_url'] is not None:
			if self.url_is_valid(results['server_url']):
				user_storage['url'] = results['server_url']
			else:
				report = '{0}: The specified URL is not valid.  Please enter it in the form of "https://127.0.0.1:1337/"'.format(report_user)
			return report

		if results['show_config']:
			if not report:
				report = ''
			report += 'Current Empire Config:\n'.format(report_user)
			report += '\tUser: {0}\n'.format(user_storage.get('user', 'None'))
			report += '\tPassword: {0}\n'.format(user_storage.get('pass', 'None'))
			report += '\tURL: {0}\n'.format(user_storage.get('url', 'None'))
			report += '\tVerify Cert: {0}\n.'format(user_storage.get('verify_cert', 'False'))
			report += '\tPolling Enabled: {0}'.format(user_storage.get('is_enabled', 'False'))

		return report

	def cmd_empire_list(self, args, jid, is_muc):
		parser = ArgumentParserLite('empire_list', 'list listeners/agents on an Empire server')
		parser.add_argument('-l', '--listeners', dest='list_listeners', help='list listeners', action='store_true', default=False)
		parser.add_argument('-a', '--agents', dest='list_agents', help='list agents', action='store_true', default=False)
		parser.add_argument('-c', '--creds', dest='list_creds', help='list credentials in the database', action='store_true', default=False)
		parser.add_argument('-v', '--verbose', dest='verbose', help='verbose output', action='store_true', default=False)
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)

		user_jid = str(jid).split('/')[0]
		if not self.user_is_configured(user_jid):
			report = 'Sorry {0}, it looks like you do not have an Empire config yet.  Create one with the "empire_setup" module.'.format(user_jid.split('@')[0])
			return report
		empire_config = self.get_storage(user_jid)	
		api = EmpireAPI(empire_config)
		token = api.get_api_token()

		if results['list_listeners']:
			listeners_dict = api.get_listeners()
			listeners = listeners_dict['listeners']
			if len(listeners) > 1:
				report = 'There are {0} listeners available:\n'.format(str(len(listeners)))
			elif len(listeners) == 1:
				report = 'There is {0} listener available:\n'.format(str(len(listeners)))
			else:
				report = 'There are {0} listeners available:\n'.format(str(len(listeners)))
			for listener in listeners:
				report += 'Name: {0}\n'.format(listener['name'])
				for listener_property in listener.keys():
					if listener_property != 'name':
						report += '{0}: {1}\n'.format(listener_property, listener[listener_property])
			return report

		if results['list_agents']:
			desired_agent_properties = ['username', 'high_integrity', 'external_ip', 'internal_ip', 'os_details', 'lastseen_time']
			agents_dict = api.get_agents()
			agents = agents_dict['agents']
			if len(agents) > 1:
				report = 'There are {0} agents connected:\n'.format(str(len(agents)))
			elif len(agents) == 1:
				report = 'There is {0} agent connected:\n'.format(str(len(agents)))
			else:
				report = 'There are {0} agents connected:\n'.format(str(len(agents)))
			for agent in agents:
				report += 'Agent: {0}\n'.format(agent['name'])
				for agent_property in agent.keys():
					if agent_property != 'name':
						if results['verbose']:
							report += '{0}: {1}\n'.format(agent_property, agent[agent_property])
						else:
							for desired_prop in desired_agent_properties:
								if agent_property == desired_prop:
									report += '{0}: {1}\n'.format(agent_property, agent[agent_property])
				report += '\n'
			return report

		if results['list_creds']:
			reported_creds = []
			report = 'Harvested Credentials:\n'
			creds_dict = api.get_creds()
			for cred in creds_dict:
				if cred['credtype'] == 'password':
					i = cred['domain'] + '\\' + cred['username']
					if i not in reported_creds:
						report += 'Domain: {0}\nUser: {1}\nPassword: {2}\n\n'.format(cred['domain'], cred['username'], cred['password'])
						reported_creds.add(i)
			return report

	def cmd_empire_shell_exec(self, args, jid, is_muc):
		parser = ArgumentParserLite('empire_shell_cmd', 'execute a shell command on empire agent')
		parser.add_argument('-a', '--agent', dest='emp_agent', help='run command on specified agent')
		parser.add_argument('-c', '--command', dest='emp_command', help='command to run')
		#parser.add_argument('-m', '--mimikatz', dest='emp_mimi', help='execute mimikatz on specified agent')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)

		user_jid = str(jid).split('/')[0]
		if not self.user_is_configured(user_jid):
			report = 'Sorry {0}, it looks like you do not have an Empire config yet.  Create one with the "empire_setup" module.'.format(user_jid.split('@')[0])
			return report
		empire_config = self.get_storage(user_jid)	
		api = EmpireAPI(empire_config)
		token = api.get_api_token()

		exec_cmd = api.exec_shell_cmd(results['emp_agent'], results['emp_command'])
		report = 'Executing command "{0}" on agent: {1}\n'.format(results['emp_command'], results['emp_agent'])
		if exec_cmd['success'] is True:
			report += 'Success!\n'
		else:
			report += 'Command execution failed.\n'
		return report

	def _empire_poll(self, *args):
		"""check each users Empire listener for new agents"""
		configured_users = []
		for user in self.bot.authorized_users:
			user = user.name
			if self.user_is_configured(user):
				configured_users.append(user)

		for user in configured_users:
			empire_config = self.get_storage(user)
			try:
				api = EmpireAPI(empire_config)
			except Exception:
				self.logger.warning('empire api instance failed to connect', exc_info=True)
				empire_config['is_enabled'] = False
				continue
			if not 'agents' in empire_config:
				empire_config['agents'] = []
			agents = api.get_agents()['agents']
			new_agent_count = 0
			for agent in agents:
				if agent['name'] not in empire_config['agents']:
					empire_config['agents'].append(agent['name'])
					new_agent_count += 1
			if new_agent_count == 0:
				continue
			report = '{0}: you have {1} new agent{2} on your listener'.format(user, new_agent_count, ('s' if new_agent_count > 1 else ''))
			self.send_report(report)

	def send_report(self, report):
		"""Displays the report in the chat window to notify the user of new agents"""
		report = IMContentMarkdown(report, 'Monospace')
		for room in self.report_rooms:
			self.bot.chat_room_join(room)
			self.bot.send_message(room, report.get_text(), mtype='groupchat', mhtml=report.get_xhtml())