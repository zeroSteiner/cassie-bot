import collections
import datetime

from cassie.argparselite import ArgumentParserLite
from cassie.imcontent import IMContentMarkdown
from cassie.templates import CassieXMPPBotModule

import requests
import smoke_zephyr.utilities as utilities

def github_repo_exists(repository):
	resp = requests.get('https://api.github.com/repos/' + repository)
	return resp.ok

class Module(CassieXMPPBotModule):
	def __init__(self, *args, **kwargs):
		super(Module, self).__init__(*args, **kwargs)
		self.repositories = []
		self.report_rooms = []
		self.reported_commits = {}
		self.reported_commits_cache_age = datetime.timedelta(1, 0)
		self.reported_pull_requests = collections.deque(maxlen=10)
		self.check_frequency = datetime.timedelta(0, 1200)  # in seconds
		self.job_id = None
		self.job_start_time = datetime.datetime.utcnow()
		self.job_start_time = datetime.datetime.utcnow()
		self.job_id = self.bot.job_manager.job_add(self.check_github_repo_activity, seconds=self.check_frequency.seconds)

	def update_options(self, config):
		self.repositories.extend(config.get('repositories', []))
		if 'room' in config:
			self.report_rooms.append(config['room'])
		check_frequency = config.get('frequency', 1200)
		if isinstance(check_frequency, str):
			check_frequency = utilities.parse_timespan(check_frequency)
		self.check_frequency = datetime.timedelta(0, check_frequency)
		return self.options

	def cmd_github(self, args, jid, is_muc):
		parser = ArgumentParserLite('github', 'monitor new commits and pull requests to a github repository')
		parser.add_argument('action', required=True, help='github plugin action (disable, enable, status)')
		if not len(args):
			action = 'status'
		else:
			results = parser.parse_args(args)
			action = results['action']
			if not action in ['disable', 'enable', 'status']:
				return 'action must be either disable, enable or status'
		response = []
		job_manager = self.bot.job_manager
		if not job_manager.job_exists(self.job_id):
			self.job_start_time = datetime.datetime.utcnow()
			self.job_id = job_manager.job_add(self.check_github_repo_activity, seconds=self.check_frequency.seconds)
		if action == 'status':
			status = job_manager.job_is_enabled(self.job_id)
			response.append("github repository monitor is {0}running".format(('' if status else 'not ')))
		elif action == 'enable':
			job_manager.job_enable(self.job_id)
			response.append('enabled the github repository monitor')
		elif action == 'disable':
			job_manager.job_disable(self.job_id)
			response.append('disabled the github repository monitor')
		return '\n'.join(response)

	def check_github_repo_activity(self, *args):
		for repository in self.repositories:
			try:
				resp = requests.get('https://api.github.com/repos/' + repository + '/commits')
				commits = resp.json()
				if len(commits):
					self.handle_commits(repository, commits)
			except:
				self.logger.error('an error occurred while processing commits', exc_info=True)
			try:
				resp = requests.get('https://api.github.com/repos/' + repository + '/pulls')
				pulls = resp.json()
				if len(pulls):
					self.handle_pull_requests(repository, pulls)
			except:
				self.logger.error('an error occurred while processing pull requests', exc_info=True)

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
			report = "GitHub {repo}: {user} pushed [commit](https://github.com/{repo}/commit/{commit_id})\n\"{msg}\"".format(repo=repository, user=committer, commit_id=commit_id, msg=message)
			self.send_report(report)

	def handle_pull_requests(self, repository, pull_rqs):
		now = datetime.datetime.utcnow()
		recent_pulls = [pull_rq for pull_rq in pull_rqs if datetime.datetime.strptime(pull_rq['created_at'], "%Y-%m-%dT%H:%M:%SZ") + self.check_frequency >= now]
		recent_pulls.reverse()
		for pull_rq in recent_pulls:
			number = pull_rq['number']
			if number in self.reported_pull_requests:
				continue
			self.reported_pull_requests.append(number)
			user = pull_rq['user']['login']
			title = pull_rq['title']
			report = "GitHub {repo}: {user} opened [PR #{number}](https://github.com/{repo}/pull/{number})\n\"{msg}\"".format(repo=repository, user=user, number=number, msg=title)
			self.send_report(report)

	def send_report(self, report):
		report = IMContentMarkdown(report, 'Monospace')
		for room in self.report_rooms:
			self.bot.chat_room_join(room)
			self.bot.send_message(room, report.get_text(), mtype='groupchat', mhtml=report.get_xhtml())
