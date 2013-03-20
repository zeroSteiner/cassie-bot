import json
import urllib2
import datetime
from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule
from cassie.imcontent import IMContentMarkdown

"""
# Example config:
[mod_github]
repository: zeroSteiner/cassie-bot
report_room: lobby@rooms.openfire
check_frequency: 1200
"""

class Module(CassieXMPPBotModule):
	def __init__(self):
		CassieXMPPBotModule.__init__(self)
		self.repositories = []
		self.report_rooms = []
		self.reported_commits = {}
		self.reported_commits_cache_age = datetime.timedelta(1, 0)
		self.check_frequency = datetime.timedelta(0, 1200) # in seconds
		self.job_id = None
		self.job_start_time = datetime.datetime.utcnow()

	def init_bot(self, *args, **kwargs):
		CassieXMPPBotModule.init_bot(self, *args, **kwargs)
		self.job_start_time = datetime.datetime.utcnow()
		self.job_id = self.bot.job_manager.job_add(self.check_repo_activity, None, hours = 0, minutes = 0, seconds = self.check_frequency.seconds)

	def config_parser(self, config):
		self.repositories.append(config.get('repository'))
		self.report_rooms.append(config.get('report_room'))
		self.check_frequency = datetime.timedelta(0, config.getint('check_frequency', 1200))
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
		if not job_manager.job_exists(self.job_id):
			self.job_start_time = datetime.datetime.utcnow()
			self.job_id = job_manager.job_add(self.check_repo_activity, None, hours = 0, minutes = 0, seconds = self.check_frequency.seconds)
		if results['enable']:
			job_manager.job_enable(self.job_id)
			response.append('enabled the github repository monitor')
		elif results['disable']:
			job_manager.job_disable(self.job_id)
			response.append('disabled the github repository monitor')
		return '\n'.join(response)

	def check_repo_activity(self, *args):
		now = datetime.datetime.utcnow()
		for repository in self.repositories:
			try:
				url_h = urllib2.urlopen('https://api.github.com/repos/' + repository + '/commits')
				data = url_h.read()
				commits = json.loads(data)
				if len(commits):
					self.handle_commits(repository, commits)
			except:
				pass
			try:
				url_h = urllib2.urlopen('https://api.github.com/repos/' + repository + '/pulls')
				data = url_h.read()
				pulls = json.loads(data)
				recent_pulls = filter(lambda pull_rq: (datetime.datetime.strptime(pull_rq['created_at'], "%Y-%m-%dT%H:%M:%SZ") + self.check_frequency >= now), pulls)
				if len(recent_pulls):
					self.handle_pull_requests(repository, recent_pulls)
			except:
				pass

	def handle_commits(self, repository, commits):
		now = datetime.datetime.utcnow()
		# Remove old commits from the cache
		commit_ids_for_removal = []
		for commit_id, commit_date in self.reported_commits.items():
			if commit_date <= now - self.reported_commits_cache_age:
				commit_ids_for_removal.append(commit_id)
		for commit_id in commit_ids_for_removal:
			del self.reported_commits[commit_id]

		commits.reverse()
		for commit in commits:
			commit_id = commit['sha']
			if commit_id in self.reported_commits:
				continue
			commit = commit['commit']
			committer = commit['committer']['name']
			commit_date = datetime.datetime.strptime(commit['committer']['date'], "%Y-%m-%dT%H:%M:%SZ")
			if commit_date <= max(self.job_start_time, now - self.reported_commits_cache_age):
				continue
			self.reported_commits[commit_id] = commit_date
			message = commit['message'].split('\n')[0]
			report = "GitHub {repo}: {user} [pushed commit](https://github.com/{repo}/commit/{commit_id})\n\"{msg}\"".format(repo = repository, user = committer, commit_id = commit_id, msg = message)
			self.send_report(report)

	def handle_pull_requests(self, repository, pull_rqs):
		pull_rqs.reverse()
		for pull_rq in pull_rqs:
			user = pull_rq['user']['login']
			number = pull_rq['number']
			title = pull_rq['title']
			report = "GitHub {repo}: {user} [opened pull request #{number}](https://github.com/{repo}/pull/{number})\n\"{msg}\"".format(repo = repository, user = user, number = number, msg = title)
			self.send_report(report)

	def send_report(self, report):
		report = IMContentMarkdown(report, 'Monospace')
		for room in self.report_rooms:
			self.bot.join_chat_room(room)
			self.bot.send_message(room, report.get_text(), mtype = 'groupchat', mhtml = report.get_xhtml())
