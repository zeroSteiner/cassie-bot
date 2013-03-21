import os
import ssl
import sys
import aiml
import time
import shlex
import pickle
import signal
import hashlib
import logging
import tarfile
import tempfile
import sleekxmpp
import urllib2
import traceback
from sleekxmpp.xmlstream import ET
from cassie.argparselite import ArgumentParserLite
from cassie.brain import Brain as CassieAimlBrain
from cassie.job import JobManager
from cassie.imcontent import IMContentText, IMContentMarkdown
from cassie import __version__

GUEST = 0
USER = 1
ADMIN = 2

class CassieUserManager(dict):
	def __init__(self, *args, **kwargs):
		self.filename = 'users.dat'
		if 'filename' in kwargs:
			self.filename = kwargs['filename']
			del kwargs['filename']
		dict.__init__(self, *args, **kwargs)
	
	def save(self):
		pickle.dump(dict((u, ud) for u, ud in self.items() if ud['type'] == 'user'), open(self.filename, 'w'))

class CassieXMPPBotAimlUpdater(sleekxmpp.ClientXMPP):
	def __init__(self, jid, password, receiver, aiml_path):
		jid = jid.split('/')[0] + '/botadmin'
		sleekxmpp.ClientXMPP.__init__(self, jid, password)
		self.register_plugin('xep_0004') # Data Forms
		self.register_plugin('xep_0030') # Service Discovery
		self.register_plugin('xep_0047') # In-band Bytestreams
		self.register_plugin('xep_0060') # PubSub
		self.register_plugin('xep_0199') # XMPP Ping
		self.ssl_version = ssl.PROTOCOL_SSLv3
		
		self.logger = logging.getLogger('cassie.bot.xmpp.aiml_updater')
		self.receiver = receiver
		self.aiml_path = aiml_path
		self.add_event_handler("session_start", self.start, threaded = True)
	
	def start(self, event):
		self.send_presence()
		self.get_roster()
		
		self.logger.info('taring the AIML directory')
		tmp_h = tempfile.TemporaryFile()
		tar_h = tarfile.open(mode = 'w:bz2', fileobj = tmp_h)
		tar_h.add(self.aiml_path)
		tar_h.close()
		tmp_h.seek(0, 0)
		data = tmp_h.read()
		tmp_h.close()
		try:
			self.logger.info('opening a stream to the receiving bot')
			stream = self['xep_0047'].open_stream(self.receiver)
			self.logger.info('sending ' + str(len(data)) + ' bytes of data to the receiving bot')
			self.logger.info('SHA-1 sum of sent data: ' + hashlib.new('sha1', data).hexdigest())
			stream.sendall(data)
			stream.send('')
			stream.close()
		except:
			self.logger.error('encountered an error while transfering the data to the receiving bot')
			self.disconnect()
			return
		self.logger.info('completed sending the data to the receiving bot')
		self.disconnect()
		return

class CassieXMPPBot(sleekxmpp.ClientXMPP):
	def __init__(self, jid, password, admin, users_file, aimls_path, botmaster, modules = {}):
		self.__shutdown__ = False
		sleekxmpp.ClientXMPP.__init__(self, jid, password)
		self.register_plugin('xep_0004') # Data Forms
		self.register_plugin('xep_0030') # Service Discovery
		self.register_plugin('xep_0045') # Multi-User Chat
		self.register_plugin('xep_0047', { 'accept_stream': self.xep_0047_accept_stream }) # In-band Bytestreams
		self.register_plugin('xep_0060') # PubSub
		self.register_plugin('xep_0199') # XMPP Ping
		self.ssl_version = ssl.PROTOCOL_SSLv3
		self.records = {'init time':0, 'last connect time':0, 'brain init time':0, 'message count':0, 'failed message count':0}
		# list of events: https://github.com/fritzy/SleekXMPP/wiki/Event-Index
		self.add_event_handler("session_start", self.session_start)
		self.add_event_handler("message", self.message)
		self.add_event_handler("ibb_stream_start", self.xep_0047_handle_stream, threaded = True)
		
		self.logger = logging.getLogger('cassie.bot.xmpp')
		self.brain = CassieAimlBrain(modules)
		self.brain.verbose(False)
		self.brain.setBotPredicate('name', 'Cassie')
		self.brain.setBotPredicate('botmaster', botmaster)
		if os.path.isfile(users_file):
			self.authorized_users = CassieUserManager(pickle.load(open(users_file, 'r')), filename = users_file)
			self.logger.info('successfully loaded ' + str(len(self.authorized_users)) + ' authorized users')
		else:
			self.logger.warning('starting with empty authorized users because no file found')
			self.authorized_users = CassieUserManager(filename = users_file)
		if not admin in self.authorized_users:
			self.authorized_users[admin] = {'lvl':ADMIN, 'type':'user'}
		self.administrator = admin
		self.aimls_path = aimls_path
		self.aiml_set_load()
		self.records['brain init time'] = time.time()
		self.records['init time'] = time.time()
		self.logger.info('bot has been successfully initialized')
		self.logger.info("the AIML kernel contains {:,} categories".format(self.brain.numCategories()))
		self.job_manager = JobManager()
		self.job_manager.start()
		
		self.bot_modules = modules
		for module in modules.itervalues():
			module.init_bot(self)
	
	def aiml_set_update(self, fileobj = None, compression = None):
		"""
		compression can be gz, bz2 or None
		"""
		compression = (compression or '*')
		tar_h = tarfile.open(mode = 'r:' + compression, fileobj = fileobj)
		if not os.access('aimls', os.R_OK):
			self.logger.error('invalid permissions to \'aimls\'')
			return None
		
		number_of_updates = 0
		all_members = tar_h.getmembers()
		aiml_folder_members = filter(lambda x: os.path.dirname(x.name).split(os.sep)[0] == 'aimls', all_members)
		if len(aiml_folder_members) == 0:
			self.logger.error('no member aimls in archive')
			tar_h.close()
			return None
		for cur_tar_obj in aiml_folder_members:
			if os.path.splitext(cur_tar_obj.name)[-1] == '.aiml':
				number_of_updates += 1
			tar_h.extract(cur_tar_obj)
		
		tar_h.close()
		self.logger.info('successfully extracted ' + str(number_of_updates) + ' AIML files')
		return number_of_updates
	
	def aiml_set_load(self):
		aimls_loaded = 0
		for root, dirs, files in os.walk(self.aimls_path):
			for name in files:
				if os.path.join(root, name).endswith('.aiml'):
					self.brain.learn(os.path.join(root, name))
					aimls_loaded += 1
		self.logger.info('successfully loaded ' + str(aimls_loaded) + ' AIML files into the kernel')
		return aimls_loaded
	
	def join_chat_room(self, room, permissions = GUEST):
		if not room in self.plugin['xep_0045'].getJoinedRooms():
			self.authorized_users[room] = {'lvl':permissions, 'type':'room'}
			self.plugin['xep_0045'].joinMUC(room, self.boundjid.user, wait = True)
			self.logger.info('joined chat room: ' + room)
	
	def leave_chat_room(self, room):
		if room in self.plugin['xep_0045'].getJoinedRooms():
			self.plugin['xep_0045'].leaveMUC(room, self.boundjid.use)
			self.logger.info('left chat room: ' + room)
			del self.authorized_users[room]
	
	def session_start(self, event):
		self.records['last connect time'] = time.time()
		self.send_presence()
		self.get_roster()
		self.logger.info('a session to the XMPP server has been established')
	
	def message(self, msg):
		if not len(msg['body']):
			return
		message = msg['body']
		jid = msg['from']
		if msg['type'] in ('chat', 'normal'):
			if not jid.bare in self.authorized_users:
				msg.reply('You Are Not Authorized To Use This Service. Registration Is Currently Closed.').send()
				self.logger.warning('unauthorized user \'' + jid.bare + '\' sent a message')
				return
		elif msg['type'] == 'groupchat':
			if jid.resource == self.boundjid.user:
				return
			if not self.boundjid.user.lower() in message.split(' ', 1)[0].lower():
				return
		else:
			return
		if message[0] in ['!', '/']:
			self.message_command(msg)
			return
		elif msg['body'][:4] == '?OTR':
			msg.reply('OTR Is Not Supported At This Time.').send()
			self.logger.debug('received OTR negotiation request from user ' + jid.bare)
			return
		message_body = msg['body'].replace('\'', '').replace('-', '')
		self.records['message count'] += 1
		sessionID = str(jid)
		self.brain.setPredicate('client-name', jid.user, sessionID)
		self.brain.setPredicate('client-name-full', str(jid), sessionID)
		self.logger.debug('received input \'' + message_body + '\' from user: ' + jid.user)
		response = self.brain.respond(message_body, jid.bare)
		if response:
			msg.reply(response).send()
		else:
			self.records['failed message count'] += 1
		return
	
	def message_command(self, msg):
		message = msg['body']
		jid = msg['from']
		user = self.authorized_users[jid.bare]
		if user['lvl'] != ADMIN:
			if msg['type'] != 'groupchat':
				return
			guser = jid.resource + '@' + jid.server.split('.', 1)[1]
			if not guser in self.authorized_users:
				return
			if self.authorized_users[guser]['lvl'] != ADMIN:
				return
		arguments = shlex.split(message)
		command = arguments.pop(0)
		command = command[1:]
		if msg['type'] == 'groupchat':
			if not command.startswith(self.boundjid.user + '.'):
				return
			if len(command.split('.')) != 2:
				return
			command = command.split('.', 1)[1]
		cmd_handler = None
		if hasattr(self, 'cmd_' + command):
			cmd_handler = getattr(self, 'cmd_' + command)
		else:
			for module in self.bot_modules.itervalues():
				if module.has_command(command):
					cmd_handler = module.get_command_handler(command)
					break
		if not cmd_handler:
			msg.reply('Command Not Found').send()
			return
		try:
			response = cmd_handler(arguments)
			if response == None:
				return
			if not isinstance(response, (IMContentMarkdown, IMContentText)):
				response = IMContentText(response)
			response.font = 'Monospace'
			self.send_message(jid.bare, response.get_text(), mtype = msg['type'], mhtml = response.get_xhtml())
			return
		except Exception as error:
			msg.reply('Failed To Execute Command, Error Name: ' + error.__class__.__name__ + ' Message: ' + error.message).send()
			self.logger.error('failed to execute command: ' + command + ' for user ' + jid.bare)
			self.logger.error('error name: ' + error.__class__.__name__ + ' message: ' + error.message)
			tb = traceback.format_exc().split(os.linesep)
			for line in tb: self.logger.error(line)
			self.logger.error(error.__repr__())
		return
	
	def cmd_aiml(self, args):
		parser = ArgumentParserLite('aiml', 'control the AIML kernel')
		parser.add_argument('-u', '--update', dest = 'update', default = None, help = 'update aiml files from URL')
		parser.add_argument('-r', '--reload', dest = 'reload', action = 'store_true', default = False, help = 'reload .aiml files')
		parser.add_argument('--reset', dest = 'reset', action = 'store_true', default = False, help = 'reset the AIML brain')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()
		response = ''
		if results['update']:
			try:
				web_h = urllib2.urlopen(results['update'])
			except:
				self.logger.error('failed to download AIML archive from URL: ' + results['update'])
				return 'Failed to open the specified URL'
			self.logger.debug('downloading AIML archive from: ' + results['update'])
			
			tmp_h = tempfile.TemporaryFile()
			chksum = hashlib.new('sha1')
			data = web_h.read()
			chksum.update(data)
			tmp_h.write(data)
			tmp_h.seek(0, 0)
			self.logger.info('done reading AIML archive, bytes read: ' + str(len(data)) + ' SHA-1 checksum: ' + chksum.hexdigest())
			
			number_of_updates = self.aiml_set_update(tmp_h)
			if number_of_updates == None:
				response += 'Failed to Extract Archive'
			else:
				response += 'Successfully Extracted ' + str(number_of_updates) + ' AIML Files\n'
				results['reload'] = True
		if results['reload']:
			number_of_aimls = self.aiml_set_load()
			response += 'Successfully reloaded ' + str(number_of_aimls) + ' AIML files into the Kernel\n'
		if results['reset']:
			self.brain.resetBrain()
			self.records['brain init time'] = time.time()
			self.logger.info('successfully reset the AIML brain')
			response += 'Successfully Reset The AIML Brain\n'
		return response
	
	def cmd_bot(self, args):
		parser = ArgumentParserLite('bot', 'control the bot')
		parser.add_argument('-l', '--log', dest = 'loglvl', action = 'store', default = None, help = 'set the bots logging level')
		parser.add_argument('--shutdown', dest = 'stop', action = 'store_true', default = False, help = 'stop the bot from running')
		parser.add_argument('--join', dest = 'join_chat_room', action = 'store', default = None, help = 'join a chat room')
		parser.add_argument('--leave', dest = 'leave_chat_room', action = 'store', default = None, help = 'leave a chat room')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()
		response = ''
		if results['loglvl']:
			results['loglvl'] = results['loglvl'].upper()
			if results['loglvl'] in ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']:
				log = logging.getLogger('')
				log.setLevel(getattr(logging, results['loglvl']))
				self.logger.info('successfully set the logging level to: ' + results['loglvl'])
				response += 'Successfully set the logging level to: ' + results['loglvl']
		if results['join_chat_room']:
			self.join_chat_room(results['join_chat_room'])
			response += 'Joined chat room: ' + results['join_chat_room']
		if results['leave_chat_room']:
			self.leave_chat_room(results['leave_chat_room'])
			response += 'Left chat room: ' + results['leave_chat_room']
		if results['stop']:
			self.request_stop()
		return response
				
	def cmd_help(self, args):
		response = 'Version: ' + __version__ + '\nAvailable Commands:\n'
		commands = []
		commands.extend(map(lambda x: x[4:], filter(lambda x: x.startswith('cmd_'), dir(self))))
		
		for module in self.bot_modules.itervalues():
			commands.extend(module.commands)
		commands.remove('help')
		response += '\n'.join(commands)
		return response
	
	def cmd_info(self, args):
		MINUTE = 60
		HOUR = 60 * MINUTE
		DAY = 24 * HOUR
		
		now = int(time.time())
		response = 'Cassie Information:\n'
		response += '== General Information ==\n'
		response += 'Version: ' + __version__ + '\n'
		response += 'PID: ' + str(os.getpid()) + '\n'
		response += "Number of Messages: {:,}\n".format(self.records['message count'])
		response += "Number of Failed Messages: {:,}\n".format(self.records['failed message count'])
		if self.records['message count'] != 0:
			response += "Message Success Rate: {:.2f}%\n".format((float(self.records['message count'] - self.records['failed message count']) / float(self.records['message count'])) * 100)
		response += "Number of Categories in the AIML Kernel: {:,}\n".format(self.brain.numCategories())
		response += "Number of Jobs: Enabled: {:,} Total: {:,}\n".format(self.job_manager.job_count_enabled(), self.job_manager.job_count())
		if len(self.bot_modules):
			response += 'Loaded Modules:'
			response += '\n    ' + "\n    ".join(self.bot_modules.keys())
			response += '\n'
		
		response += '\n== Uptime Information ==\n'
		response += 'Core Initialization Time: ' + time.asctime(time.localtime(self.records['init time'])) + '\n'
		then = int(self.records['init time'])
		days = (now - then) / DAY
		hours = ((now - then) % DAY) / HOUR
		minutes = (((now - then) % DAY) % HOUR) / MINUTE
		seconds = (((now - then) % DAY) % HOUR) % MINUTE
		response += "Core Uptime: {:,} days {} hours {} minutes {} seconds\n".format(days, hours, minutes, seconds)
		
		response += 'Last AIML Brain Initialization Time: ' + time.asctime(time.localtime(self.records['brain init time'])) + '\n'
		then = int(self.records['brain init time'])
		days = (now - then) / DAY
		hours = ((now - then) % DAY) / HOUR
		minutes = (((now - then) % DAY) % HOUR) / MINUTE
		seconds = (((now - then) % DAY) % HOUR) % MINUTE
		response += "AIML Brain Uptime: {:,} days {} hours {} minutes {} seconds\n".format(days, hours, minutes, seconds)
		
		response += 'Last XMPP Connect Time: ' + time.asctime(time.localtime(self.records['last connect time'])) + '\n'
		then = int(self.records['last connect time'])
		days = (now - then) / DAY
		hours = ((now - then) % DAY) / HOUR
		minutes = (((now - then) % DAY) % HOUR) / MINUTE
		seconds = (((now - then) % DAY) % HOUR) % MINUTE
		response += "XMPP Uptime: {:,} days {} hours {} minutes {} seconds\n".format(days, hours, minutes, seconds)
		return response[:-1]
	
	def cmd_user(self, args):
		parser = ArgumentParserLite('user', 'add/delete/modify users')
		parser.add_argument('-a', '--add', dest = 'add user', action = 'store', default = None, help = 'add user')
		parser.add_argument('-d', '--del', dest = 'delete user', action = 'store', default = None, help = 'delete user')
		parser.add_argument('-l', '--lvl', dest = 'permissions', action = 'store', default = 'USER', help = 'permission level of user')
		parser.add_argument('-s', '--show', dest = 'show', action = 'store_true', default = False, help = 'show the user database')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()
		response = ''
		if not results['permissions'].upper() in ['GUEST', 'USER', 'ADMIN']:
			return 'Invalid privilege level'
		else:
			privilege_level = {'GUEST':GUEST, 'USER':USER, 'ADMIN':ADMIN}[results['permissions'].upper()]
		if results['add user']:
			if not results['add user'] in self.authorized_users:
				self.authorized_users[results['add user']] = {'lvl':privilege_level, 'type':'user'}
				response += 'Successfully Added User: ' + results['add user']
			else:
				response += 'Can Not Add Already Authorized User'
		if results['delete user']:
			if not results['delete user'] in self.authorized_users:
				response += 'Can Not Delete Non-Authorized User'
			elif results['delete user'] == self.brain.getBotPredicate('botmaster'):
				response += 'Can Not Delete The Bot Master'
			else:
				del self.authorized_users[results['delete user']]
				response += 'Successfully Deleted User: ' + results['delete user']
		if results['show']:
			if not response:
				response += '\n'
			response += 'User Listing:\n'
			for user, user_desc in self.authorized_users.items():
				response += user_desc['type'].upper() + ' ' + user + ' ' + {0:'Guest', 1:'User', 2:'Admin'}[user_desc['lvl']] + '\n'
			response += '\n'
		if not response:
			return 'Missing Action'
		response += '\n'
		try:
			self.authorized_users.save()
		except:
			response += 'Failed To Save User Database'
		return response
	
	def request_stop(self, sig = None, other = None):
		if sig == None:
			self.logger.warning('received shutdown command, proceeding to stop')
		elif sig == signal.SIGTERM:
			self.logger.warning('received SIGTERM signal, proceeding to stop')
		elif sig == signal.SIGINT:
			self.logger.warning('received SIGINT signal, proceeding to stop')
		elif sig == signal.SIGHUP:
			self.logger.warning('received SIGHUP signal, proceeding to stop')
		self.__shutdown__ = True
		self.disconnect()
		if hasattr(self.brain, 'stop'):
			self.brain.stop()
		try:
			self.authorized_users.save()
			self.logger.info('successfully dumped authorized users to file')
		except:
			self.logger.error('failed to dump authorized users to file on clean up')
		self.job_manager.stop()
		sys.exit(1)
	
	def xep_0047_accept_stream(self, msg):
		if not msg['from'].bare in self.authorized_users:
			return False
		user = self.authorized_users[msg['from'].bare]
		if user['lvl'] < ADMIN:
			return False
		if msg['from'].resource != '/botadmin':
			return False
		return True
	
	def xep_0047_handle_stream(self, stream):
		self.logger.info('stream opened: ' + stream.sid + ' from: ' + stream.receiver.bare)
		tmp_h = tempfile.TemporaryFile()
		
		chksum = hashlib.new('sha1')
		size = 0
		
		data = stream.read()
		while data:
			size += len(data)
			chksum.update(data)
			tmp_h.write(data)
			data = stream.read(timeout = 5)
		tmp_h.seek(0, 0)
		self.logger.info('done reading AIML archive, bytes read: ' + str(size) + ' SHA-1 checksum: ' + chksum.hexdigest())
		self.aiml_set_update(tmp_h, compression = 'bz2')
		tmp_h.close()
