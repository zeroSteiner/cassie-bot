import os
import ssl
import sys
import aiml
import time
import uuid
import shlex
import pickle
import signal
import hashlib
import logging
import tarfile
import urllib2
import datetime
import tempfile
import sleekxmpp
import threading
import traceback
from sleekxmpp.xmlstream import ET
from cassie.argparselite import ArgumentParserLite
from cassie.brain import Brain as CassieAimlBrain
from cassie.job import JobManager, JobRequestDelete
from cassie.imcontent import IMContentText, IMContentMarkdown
from cassie import __version__

GUEST = 0
USER = 1
ADMIN = 2
USER_LVL_NAME_TO_INT = {'GUEST':GUEST, 'USER':USER, 'ADMIN':ADMIN}
USER_LVL_INT_TO_NAME = {GUEST:'GUEST', USER:'USER', ADMIN:'ADMIN'}

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
	def __init__(self, jid, password, target_bot, aimls_path):
		jid = jid.split('/')[0] + '/botadmin'
		sleekxmpp.ClientXMPP.__init__(self, jid, password)
		self.register_plugin('xep_0004') # Data Forms
		self.register_plugin('xep_0030') # Service Discovery
		self.register_plugin('xep_0047') # In-band Bytestreams
		self.register_plugin('xep_0060') # PubSub
		self.register_plugin('xep_0199') # XMPP Ping
		self.ssl_version = ssl.PROTOCOL_SSLv3
		
		self.logger = logging.getLogger('cassie.bot.xmpp.aimls_updater')
		self.target_bot = target_bot
		self.aimls_path = aimls_path
		self.aimls_reloaded = threading.Event()
		self.add_event_handler("session_start", self.session_start, threaded = True)
		self.add_event_handler("message", self.message, threaded = True)
	
	def session_start(self, event):
		self.send_presence()
		self.get_roster()
		
		self.logger.info('taring the AIML directory')
		tmp_h = tempfile.TemporaryFile()
		tar_h = tarfile.open(mode = 'w:bz2', fileobj = tmp_h)
		os.chdir(self.aimls_path)
		tar_h.add('.')
		tar_h.close()
		tmp_h.seek(0, 0)
		data = tmp_h.read()
		tmp_h.close()
		try:
			self.logger.info('opening a stream to the receiving bot')
			stream = self['xep_0047'].open_stream(self.target_bot)
			self.logger.info('sending ' + str(len(data)) + ' bytes of data to the receiving bot')
			self.logger.info('SHA-1 sum of sent data: ' + hashlib.new('sha1', data).hexdigest())
			stream.sendall(data)
			stream.close()
		except:
			self.logger.error('encountered an error while transfering the data to the receiving bot')
			self.disconnect()
			return
		self.logger.info('completed sending the data to the receiving bot')
		self.send_message(self.target_bot, '!aiml --reload', mtype = 'chat')
		if self.aimls_reloaded.wait(10.0):
			self.logger.info('the receiving bot successfully reloaded the aiml set')
		else:
			self.logger.error('the receiving bot failed to reload the aiml set')
		self.disconnect()
		return

	def message(self, msg):
		if not msg['type'] in ('chat', 'normal'):
			return
		if not msg['from'] == self.target_bot:
			return
		message = msg['body'].lower()
		self.logger.debug('received message: ' + msg['body'])
		if message.startswith('success'):
			self.aimls_reloaded.set()
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
		users_file = os.path.abspath(users_file)
		if os.path.isfile(users_file):
			self.authorized_users = CassieUserManager(pickle.load(open(users_file, 'r')), filename = users_file)
			self.logger.info('successfully loaded ' + str(len(self.authorized_users)) + ' authorized users')
		else:
			self.logger.warning('starting with empty authorized users because no file found')
			self.authorized_users = CassieUserManager(filename = users_file)
		if not admin in self.authorized_users:
			self.authorized_users[admin] = {'lvl':ADMIN, 'type':'user'}
		self.administrator = admin
		self.aimls_path = os.path.abspath(aimls_path)
		self.aiml_set_load()
		self.records['brain init time'] = time.time()
		self.records['init time'] = time.time()
		self.logger.info('bot has been successfully initialized')
		self.logger.info("the AIML kernel contains {:,} categories".format(self.brain.numCategories()))
		self.job_manager = JobManager(logger_name = 'cassie.bot.xmpp.job_manager')
		self.job_manager.start()
		
		self.custom_message_handlers = {}
		self.custom_message_handler_lock = threading.RLock()
		self.custom_message_handler_reaper_job_id = None
		
		self.bot_modules = modules
		self.command_permissions = {}
		for command in map(lambda x: x[4:], filter(lambda x: x.startswith('cmd_'), dir(self))):
			self.command_permissions[command] = ADMIN
		for module in self.bot_modules.itervalues():
			for command in module.commands:
				self.command_permissions[command] = ADMIN
		self.command_handler_set_permission('help', 'user')
		
		for module in modules.itervalues():
			module.init_bot(self)
	
	def aiml_set_update(self, fileobj = None, compression = None):
		"""
		compression can be gz, bz2 or None
		"""
		compression = (compression or '*')
		tar_h = tarfile.open(mode = 'r:' + compression, fileobj = fileobj)
		if not os.access(self.aimls_path, os.R_OK):
			self.logger.error('invalid permissions to \'' + self.aimls_path + '\'')
			return None
		
		number_of_updates = 0
		all_members = tar_h.getmembers()
		aiml_members = filter(lambda x: os.path.splitext(x.name)[-1] == '.aiml', all_members)
		if len(aiml_members) == 0:
			self.logger.error('no member aimls in archive')
			tar_h.close()
			return None
		for cur_tar_obj in aiml_members:
			tar_h.extract(cur_tar_obj, path = self.aimls_path)
		
		tar_h.close()
		self.logger.info('successfully extracted ' + str(len(aiml_members)) + ' AIML files')
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
	
	def chat_room_join(self, room, permissions = USER):
		if room in self.plugin['xep_0045'].getJoinedRooms():
			return
		# rooms are technically authorized users
		self.authorized_users[room] = {'lvl':permissions, 'type':'room'}
		self.plugin['xep_0045'].joinMUC(room, self.boundjid.user, wait = True)
		self.logger.info('joined chat room: ' + room)
	
	def chat_room_leave(self, room):
		if not room in self.plugin['xep_0045'].getJoinedRooms():
			return
		self.plugin['xep_0045'].leaveMUC(room, self.boundjid.use)
		self.logger.info('left chat room: ' + room)
		del self.authorized_users[room]
	
	def session_start(self, event):
		self.records['last connect time'] = time.time()
		self.send_presence()
		self.get_roster()
		self.logger.info('a session to the XMPP server has been established')
		rooms_to_rejoin = []
		for room_name, details in self.authorized_users.items():
			if details['type'] != 'room':
				continue
			rooms_to_rejoin.append((room_name, details['lvl']))
		for room_name, permissions in rooms_to_rejoin:
			self.chat_room_leave(room_name)
			self.chat_room_join(room_name, permissions)
	
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

		session_id = str(jid) # session_id as used in the AIML brain
		if message[0] in ['!', '/']:
			self.message_command(msg)
			return
		elif msg['body'][:4] == '?OTR':
			msg.reply('OTR Is Not Supported At This Time.').send()
			self.logger.debug('received OTR negotiation request from user ' + session_id)
			return
		
		with self.custom_message_handler_lock:
			if session_id in self.custom_message_handlers:
				expiration = self.custom_message_handlers[session_id]['expiration']
				if expiration <= datetime.datetime.utcnow():
					self.custom_message_handler_del(session_id)
				else:
					handler_info = self.custom_message_handlers[session_id]
					custom_handler = handler_info['callback']
					if isinstance(handler_info['lifespan'], datetime.timedelta): # if the lifespan is set, adjust the expiration
						handler_info['expiration'] = datetime.datetime.utcnow() + handler_info['lifespan']
					try:
						response = custom_handler(msg['body'], jid)
					except Exception as err:
						self.logger.error('custom message handler error - name: ' + custom_handler.__name__ + ' jid: ' + str(jid.jid) + ' exception: ' + err.__class__.__name__)
						response = 'the message handler encountered an error'
					self.send_message_formatted(jid, response, msg['type'])
					return
		
		message_body = msg['body'].replace('\'', '').replace('-', '')
		self.records['message count'] += 1
		self.brain.setPredicate('client-name', str(jid.user), session_id)
		self.logger.debug('received input \'' + message_body + '\' from user: ' + session_id)
		response = self.brain.respond(message_body, session_id)
		if response:
			msg.reply(response).send()
		else:
			self.records['failed message count'] += 1
		return
	
	def send_message_formatted(self, mto, mbody, mtype = None):
		if not mbody:
			return
		if not isinstance(mbody, (IMContentMarkdown, IMContentText)):
			mbody = IMContentText(mbody)
		mbody.font = 'Monospace'
		if mtype == 'groupchat':
			self.send_message(mto.bare, mbody.get_text(), mtype = mtype, mhtml = mbody.get_xhtml())
		else:
			self.send_message(mto, mbody.get_text(), mtype = mtype, mhtml = mbody.get_xhtml())
		return
	
	def command_handler_get(self, command, userlvl):
		if userlvl < self.command_permissions.get(command, ADMIN):
			return None
		cmd_handler = None
		if hasattr(self, 'cmd_' + command):
			cmd_handler = getattr(self, 'cmd_' + command)
		else:
			for module in self.bot_modules.itervalues():
				if module.has_command(command):
					cmd_handler = module.get_command_handler(command)
					break
		return cmd_handler
	
	def command_handler_set_permission(self, command, userlvl):
		if isinstance(userlvl, str):
			userlvl = userlvl.upper()
			userlvl = USER_LVL_NAME_TO_INT[userlvl]
		elif not isinstance(userlvl, (int, long)):
			raise Exception('invalid userlvl type')
		if not command in self.command_permissions:
			raise Exception('can not set permission for unknown command: ' + repr(command))
		self.command_permissions[command] = userlvl
	
	def message_command(self, msg):
		message = msg['body']
		jid = msg['from']
		user = self.authorized_users[jid.bare]
		user_lvl = user['lvl']
		if msg['type'] == 'groupchat':
			guser = jid.resource + '@' + jid.server.split('.', 1)[1]
			if not guser in self.authorized_users:
				return
			user_lvl = self.authorized_users[guser]['lvl']
		arguments = shlex.split(message)
		command = arguments.pop(0)
		command = command[1:]
		if msg['type'] == 'groupchat':
			if not command.startswith(self.boundjid.user + '.'):
				return
			if len(command.split('.')) != 2:
				return
			command = command.split('.', 1)[1]
		cmd_handler = self.command_handler_get(command, user_lvl)
		if not cmd_handler:
			msg.reply('Command Not Found').send()
			return
		try:
			response = cmd_handler(arguments, jid)
			self.send_message_formatted(jid, response, msg['type'])
			return
		except Exception as error:
			msg.reply('Failed To Execute Command, Error Name: ' + error.__class__.__name__ + ' Message: ' + error.message).send()
			self.logger.error('failed to execute command: ' + command + ' for user ' + jid.bare)
			self.logger.error('error name: ' + error.__class__.__name__ + ' message: ' + error.message)
			tb = traceback.format_exc().split(os.linesep)
			for line in tb: self.logger.error(line)
			self.logger.error(error.__repr__())
		return
	
	def cmd_aiml(self, args, jid):
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
	
	def cmd_bot(self, args, jid):
		parser = ArgumentParserLite('bot', 'control the bot')
		parser.add_argument('-l', '--log', dest = 'loglvl', action = 'store', default = None, help = 'set the bots logging level')
		parser.add_argument('--shutdown', dest = 'stop', action = 'store_true', default = False, help = 'stop the bot from running')
		parser.add_argument('--join', dest = 'chat_room_join', action = 'store', default = None, help = 'join a chat room')
		parser.add_argument('--leave', dest = 'chat_room_leave', action = 'store', default = None, help = 'leave a chat room')
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
		if results['chat_room_join']:
			self.chat_room_join(results['chat_room_join'])
			response += 'Joined chat room: ' + results['chat_room_join']
		if results['chat_room_leave']:
			self.chat_room_leave(results['chat_room_leave'])
			response += 'Left chat room: ' + results['chat_room_leave']
		if results['stop']:
			self.request_stop()
		return response
	
	def cmd_help(self, args, jid):
		user = self.authorized_users[jid.bare]
		user_lvl = user['lvl']

		response = 'Version: ' + __version__ + '\nAvailable Commands:\n'
		commands = []
		for command in map(lambda x: x[4:], filter(lambda x: x.startswith('cmd_'), dir(self))):
			if self.command_handler_get(command, user_lvl):
				commands.append(command)
		for module in self.bot_modules.itervalues():
			for command in module.commands:
				if self.command_handler_get(command, user_lvl):
					commands.append(command)
		if 'help' in commands:
			commands.remove('help')
		response += '\n'.join(commands)
		return response
	
	def cmd_info(self, args, jid):
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
	
	def cmd_user(self, args, jid):
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
		if not results['permissions'].upper() in USER_LVL_NAME_TO_INT:
			return 'Invalid privilege level'
		else:
			privilege_level = USER_LVL_NAME_TO_INT[results['permissions'].upper()]
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
				response += user_desc['type'].upper() + ' ' + user + ' ' + USER_LVL_INT_TO_NAME[user_desc['lvl']].capitalize() + '\n'
			response += '\n'
		if not response:
			return 'Missing Action'
		response += '\n'
		try:
			self.authorized_users.save()
		except:
			response += 'Failed To Save User Database'
		return response
	
	def custom_message_handler_add(self, jid, callback, expiration, reset_expiration = True):
		jid = str(jid)
		handler_id = None
		if isinstance(expiration, (int, long, float)):
			lifespan = datetime.timedelta(0, expiration)
			expiration = datetime.datetime.utcnow() + lifespan
		elif isinstance(expiration, datetime.timedelta):
			lifespan = expiration
			expiration = datetime.datetime.utcnow() + expiration
		else:
			raise Exception('unknown expiration format')
		with self.custom_message_handler_lock:
			handler_id = uuid.uuid4()
			self.logger.debug('setting custom message handler for ' + jid + ' to ' + callback.__name__)
			if not reset_expiration:
				lifespan = None
			self.custom_message_handlers[jid] = {'callback':callback, 'expiration':expiration, 'lifespan':lifespan, 'handler_id':handler_id}
		# start the reaper if necessary
		if self.custom_message_handler_reaper_job_id == None:
			self.custom_message_handler_reaper_job_id = self.job_manager.job_add(self.custom_message_handler_reaper, minutes = 3)
		elif not self.job_manager.job_exists(self.custom_message_handler_reaper_job_id):
			self.custom_message_handler_reaper_job_id = self.job_manager.job_add(self.custom_message_handler_reaper, minutes = 3)
		return handler_id
	
	def custom_message_handler_exists(self, jid = None, handler_id = None):
		if not (bool(jid) ^ bool(handler_id)):
			raise Exception('specify either jid or handler_id')
		with self.custom_message_handler_lock:
			if jid:
				if jid in self.custom_message_handlers:
					return True
			if handler_id:
				if not isinstance(handler_id, uuid.UUID):
					handler_id = uuid.UUID(handler_id)
				for jid, handler in self.custom_message_handlers.items():
					if handler['handler_id'] == handler_id:
						return True
		return False
	
	def custom_message_handler_del(self, jid):
		jid = str(jid)
		with self.custom_message_handler_lock:
			if jid in self.custom_message_handlers:
				del self.custom_message_handlers[jid]
				self.logger.debug('deleting custom message handler for ' + jid)
	
	def custom_message_handler_reaper(self):
		with self.custom_message_handler_lock:
			handlers_for_removal = []
			for jid, handler in self.custom_message_handlers.items():
				expiration = handler['expiration']
				if expiration <= datetime.datetime.utcnow():
					handlers_for_removal.append(jid)
			for jid in handlers_for_removal:
				self.custom_message_handler_del(jid)
			if not self.custom_message_handlers:
				self.custom_message_handler_reaper_job_id = None
				return JobRequestDelete()
		return None
	
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
		try:
			for i in range(1):
				if not msg['from'].bare in self.authorized_users:
					break
				user = self.authorized_users[msg['from'].bare]
				if user['lvl'] != ADMIN:
					break
				if msg['from'].resource != 'botadmin':
					break
				self.logger.warning('accepting an IBB stream from ' + msg['from'].bare)
				return True
			self.logger.warning('rejecting an IBB stream from ' + msg['from'].bare)
		except:
			self.logger.error('an error occured while accepting an IBB stream, it was rejected')
			return False
	
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
