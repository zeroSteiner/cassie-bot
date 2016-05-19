import datetime

from cassie.argparselite import ArgumentParserLite
from cassie.imcontent import IMContentMarkdown
from cassie.templates import CassieXMPPBotModule

try:
	import requests
except ImportError:
	print('Failed to import "requests" module.')

class EmpireAPI(object):
	"""Class to provide access to various functionality exposed through the Empire API"""

	def __init__(self, empire_config):
		"""Initialize a new instance of the EmpireAPI class"""
		self.username = empire_config['user']
		self.password = empire_config['pass']
		self.api_base_url = empire_config['url'] + '/api/'
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
		try:
			response = requests.get(url, headers=self.json_request_headers, verify=self.verify_server_cert)
		except requests.exceptions.SSLError:
			return 'Server certificate validation failed.'
		return response.json()

	def send_post_request(self, url, json):
		"""Send a POST request to the Empire server API """
		try:
			response = requests.post(url, headers=self.json_request_headers, json=json, verify=self.verify_server_cert)
		except requests.exceptions.SSLError:
			return 'Server certificate verification failed.'
		return response.json()

	def get_agents(self):
	    """Get the details of current agents on the server"""
	    server_url = self.api_base_url + 'agents?token={0}'.format(self._token)
	    response = self.send_get_request(server_url)
	    return response

class Module(CassieXMPPBotModule):
	def __init__(self, *args, **kwargs):
		super(Module, self).__init__(*args, **kwargs)
		self.report_rooms = []
		self.check_frequency = datetime.timedelta(0, 180)  # in seconds
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
		return 'url' in storage and storage.get('is_online', False)

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
				empire_config['is_online'] = False
				continue
			if not 'agents' in empire_config:
				empire_config['agents'] = []
			agents = api.get_agents()['agents']
			new_agent_count = 0
			for new_agent_count, agent in enumerate(agents, 1):
				if agent['name'] not in empire_config['agents']:
					empire_config['agents'].append(agent['name'])
			if len(new_agent_count) == 0:
				continue
			report = '{0}: you have {1} new agent{2} on your listener'.format(user, new_agent_count, ('s' if len(new_agent_count) > 1 else ''))
			self.send_report(report)

	def send_report(self, report):
		"""Displays the report in the chat window to notify the user of new agents"""
		report = IMContentMarkdown(report, 'Monospace')
		for room in self.report_rooms:
			self.bot.chat_room_join(room)
			self.bot.send_message(room, report.get_text(), mtype='groupchat', mhtml=report.get_xhtml())