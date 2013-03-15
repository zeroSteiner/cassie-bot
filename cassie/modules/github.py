import json
import urllib2
import datetime
from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

"""
# Example config:
[mod_github]
repository: zeroSteiner/cassie-bot
report_room: lobby@rooms.openfire
"""

class Module(CassieXMPPBotModule):
	def __init__(self):
		CassieXMPPBotModule.__init__(self)
		self.repositories = []
		self.report_rooms = []
		self.check_frequency = 600 # in seconds
		self.job_id = None

	def init_bot(self, *args, **kwargs):
		CassieXMPPBotModule.init_bot(self, *args, **kwargs)
		self.job_id = self.bot.job_manager.job_add(self.check_repo, None, hours = 0, minutes = 0, seconds = self.check_frequency)

	def config_parser(self, config):
		self.repositories.append(config.get('repository'))
		self.report_rooms.append(config.get('report_room'))
		return self.options

	def cmd_github(self, args):
		parser = ArgumentParserLite('github', 'monitor commits to a github repository')
		parser.add_argument('--enable', dest = 'enable', action = 'store_true', default = None, help = 'enable this service')
		parser.add_argument('--disable', dest = 'disable', action = 'store_true', default = None, help = 'disable this service')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()
		response = []
		if results['enable'] and results['disable']:
			return 'please select either enable or disable'
		elif results['enable'] != True and results['disable'] != True:
			return 'please select either enable or disable'
		job_manager = self.bot.job_manager
		if results['enable']:
			job_manager.job_enable(self.job_id)
			response.append('enabled the github repository monitor')
		elif results['disable']:
			job_manager.job_disable(self.job_id)
			response.append('disabled the github repository monitor')
		return '\n'.join(response)

	def check_repo(self, *args):
		for repository in self.repositories:
			try:
				since_timestamp = (datetime.datetime.utcnow() - datetime.timedelta(0, self.check_frequency)).strftime("%Y-%m-%dT%H:%M:%SZ")
				url_h = urllib2.urlopen('https://api.github.com/repos/' + repository + '/commits?since=' + since_timestamp)
				data = url_h.read()
				commits = json.loads(data)
				if len(commits):
					self.handle_commits(repository, commits)
			except:
				break

	def handle_commits(self, repository, commits):
		commits.reverse()
		for commit in commits:
			commit = commit['commit']
			committer = commit['committer']['name']
			message = commit['message'].split('\n')[0]
			report = "GitHub: {0} pushed to {1} \"{2}\"".format(committer, repository, message)
			for room in self.report_rooms:
				self.bot.join_chat_room(room)
				self.bot.send_message(room, report, mtype = 'groupchat')
