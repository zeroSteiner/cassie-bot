import collections
import datetime
import hashlib
import logging
import shlex
import signal
import ssl
import sys
import tempfile
import threading
import time
import uuid

from cassie import __version__
from cassie.errors import *
from cassie.imcontent import IMContentText, IMContentMarkdown
from cassie.bot import users

import sleekxmpp
from smoke_zephyr.job import JobManager, JobRequestDelete

class CassieXMPPBot(sleekxmpp.ClientXMPP):
	def __init__(self, jid, password, admin, users_file, modules=None):
		self.__shutdown__ = False
		sleekxmpp.ClientXMPP.__init__(self, jid, password)
		self.register_plugin('xep_0004')  # data forms
		self.register_plugin('xep_0030')  # service discovery
		self.register_plugin('xep_0045')  # multi-user chat
		self.register_plugin('xep_0047', {'accept_stream': self.xep_0047_accept_stream})
		self.register_plugin('xep_0060')  # pubsub
		self.register_plugin('xep_0199')  # xmpp ping
		self.ssl_version = ssl.PROTOCOL_TLSv1
		self.records = {'init time': 0, 'last connect time': 0, 'message count': 0, 'failed message count': 0}
		# list of events: https://github.com/fritzy/SleekXMPP/wiki/Event-Index
		self.add_event_handler('session_start', self.session_start)
		self.add_event_handler('message', self.message)
		self.add_event_handler('ibb_stream_start', self.xep_0047_handle_stream, threaded=True)

		self.logger = logging.getLogger('cassie.bot.xmpp')
		self.authorized_users = users.UserManager(filename=users_file)
		if not admin in self.authorized_users:
			self.authorized_users[admin] = users.User(admin, level=users.LVL_ADMIN)
		self.administrator = admin

		self.records['init time'] = time.time()
		self.logger.info('bot has been successfully initialized')
		self.job_manager = JobManager()
		self.job_manager.start()

		self.custom_message_handlers = {}
		self.custom_message_handler_lock = threading.RLock()
		self.custom_message_handler_reaper_job_id = None

		self.bot_modules = modules or []
		self.command_permissions = collections.defaultdict(lambda: users.LVL_ADMIN)
		self.command_handler_set_permission('help', 'user')

	def chat_room_join(self, room, permissions=users.LVL_ROOM):
		if room in self.plugin['xep_0045'].getJoinedRooms():
			return
		# rooms are technically authorized users
		self.authorized_users[room] = users.Room(room, permissions)
		if self.is_connected:
			self.plugin['xep_0045'].joinMUC(room, self.boundjid.user, wait=True)
			self.logger.info('joined chat room: ' + room)

	def chat_room_leave(self, room):
		if not room in self.plugin['xep_0045'].getJoinedRooms():
			return
		self.plugin['xep_0045'].leaveMUC(room, self.boundjid.user)
		self.logger.info('left chat room: ' + room)
		del self.authorized_users[room]

	@property
	def is_connected(self):
		return self.state.current_state() == 'connected'

	def session_start(self, event):
		self.records['last connect time'] = time.time()
		self.send_presence()
		self.get_roster()
		self.logger.info('a session to the XMPP server has been established')
		rooms_to_rejoin = []
		for room in self.authorized_users:
			if room.type != 'room':
				continue
			rooms_to_rejoin.append(room)
		for room in rooms_to_rejoin:
			self.chat_room_leave(room.name)
			self.chat_room_join(room.name, room.level)

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

		session_id = str(jid)  # session_id as used in the AIML brain
		if message[0] in ('!', '/'):
			self.message_command(msg)
			return
		elif msg['body'][:4] == '?OTR':
			msg.reply('OTR Is Not Supported At This Time.').send()
			self.logger.debug('received OTR negotiation request from user ' + session_id)
			return

		if msg['type'] == 'groupchat':
			message = message.split(' ', 1)
			if len(message) != 2:
				return
			message = message[1]
			session_id = str(jid.bare)

		with self.custom_message_handler_lock:
			if session_id in self.custom_message_handlers:
				expiration = self.custom_message_handlers[session_id]['expiration']
				if expiration <= datetime.datetime.utcnow():
					self.custom_message_handler_del(jid=session_id)
				else:
					handler_info = self.custom_message_handlers[session_id]
					custom_handler = handler_info['callback']
					if isinstance(handler_info['lifespan'], datetime.timedelta): # if the lifespan is set, adjust the expiration
						handler_info['expiration'] = datetime.datetime.utcnow() + handler_info['lifespan']
					try:
						response = custom_handler(message, jid, handler_info['handler_id'])
					except Exception as err:
						self.logger.error('custom message handler error - name: ' + custom_handler.__name__ + ' jid: ' + str(jid.jid) + ' exception: ' + err.__class__.__name__, exc_info=True)
						response = 'the message handler encountered an error'
					self.send_message_formatted(jid, response, msg['type'])
					return

		message_body = message.replace('\'', '').replace('-', '')
		self.records['message count'] += 1
		self.logger.debug('received input \'' + message_body + '\' from user: ' + session_id)
		self.records['failed message count'] += 1
		return

	def module_load(self, module_name, config=None):
		self.logger.info('loading xmpp module: ' + module_name)
		try:
			module = __import__('cassie.modules.' + module_name, None, None, ['Module'])
			module_instance = module.Module(self)
		except Exception as err:
			self.logger.error('loading module: ' + module_name + ' failed with error: ' + err.__class__.__name__, exc_info=True)
			return False
		if config:
			module_instance.update_options(config)
		self.bot_modules.append(module_instance)
		return True

	def send_message_formatted(self, mto, mbody, mtype=None):
		if not mbody:
			return
		if not isinstance(mbody, (IMContentMarkdown, IMContentText)):
			mbody = IMContentText(mbody)
		mbody.font = 'Monospace'
		if mtype == 'groupchat':
			self.send_message(mto.bare, mbody.get_text(), mtype=mtype, mhtml=mbody.get_xhtml())
		else:
			self.send_message(mto, mbody.get_text(), mtype=mtype, mhtml=mbody.get_xhtml())
		return

	def command_handler_get(self, command, userlvl):
		if userlvl > self.command_permissions[command]:
			return None
		cmd_handler = None
		if hasattr(self, 'cmd_' + command):
			cmd_handler = getattr(self, 'cmd_' + command)
		else:
			for module in self.bot_modules:
				if module.has_command(command):
					cmd_handler = module.get_command_handler(command)
					break
		return cmd_handler

	def command_handler_set_permission(self, command, userlvl):
		if isinstance(userlvl, str):
			userlvl = users.get_level_by_name(userlvl)
		elif not isinstance(userlvl, int):
			raise TypeError('invalid userlvl type')
		self.command_permissions[command] = userlvl

	def message_command(self, msg):
		message = msg['body']
		jid = msg['from']
		user = self.authorized_users[jid.bare]
		user_lvl = user.level
		if msg['type'] == 'groupchat':
			guser = jid.resource + '@' + jid.server.split('.', 1)[1]
			if not guser in self.authorized_users:
				return
			user_lvl = self.authorized_users[guser].level
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
			response = cmd_handler(arguments, jid, (msg['type'] == 'groupchat'))
			self.send_message_formatted(jid, response, msg['type'])
			return
		except CassieCommandError as error:
			self.logger.warning('command error command: ' + command + ' for user ' + jid.bare)
			self.send_message_formatted(jid, error.message, msg['type'])
		except Exception as error:
			error_message = getattr(error, 'message', 'N/A')
			msg.reply('Failed To Execute Command, Error Name: ' + error.__class__.__name__ + ' Message: ' + error_message).send()
			self.logger.error('failed to execute command: ' + command + ' for user ' + jid.bare)
			self.logger.error('error name: ' + error.__class__.__name__ + ' message: ' + error_message, exc_info=True)
		return

	def cmd_help(self, args, jid, is_muc):
		user = self.authorized_users[jid.bare]

		response = 'Cassie Version: ' + __version__ + '\nAvailable Commands:\n'
		commands = []
		for command in dir(self):
			if not command.startswith('cmd_'):
				continue
			command = command[4:]
			if self.command_handler_get(command, user.level):
				commands.append(command)
		for module in self.bot_modules:
			for command in module.commands:
				if self.command_handler_get(command, user.level):
					commands.append(command)
		if 'help' in commands:
			commands.remove('help')
		response += '\n'.join(commands)
		return response

	def custom_message_handler_add(self, jid, callback, expiration, reset_expiration=True):
		jid = str(jid)
		handler_id = None
		if isinstance(expiration, (int, float)):
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
			self.custom_message_handlers[jid] = {'callback': callback, 'expiration': expiration, 'lifespan': lifespan, 'handler_id': handler_id}
		# start the reaper if necessary
		if self.custom_message_handler_reaper_job_id is None:
			self.custom_message_handler_reaper_job_id = self.job_manager.job_add(self.custom_message_handler_reaper, minutes=3)
		elif not self.job_manager.job_exists(self.custom_message_handler_reaper_job_id):
			self.custom_message_handler_reaper_job_id = self.job_manager.job_add(self.custom_message_handler_reaper, minutes=3)
		return handler_id

	def custom_message_handler_exists(self, jid=None, handler_id=None):
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

	def custom_message_handler_del(self, jid=None, handler_id=None, safe=False):
		if not (bool(jid) ^ bool(handler_id)):
			raise Exception('specify either jid or handler_id')
		with self.custom_message_handler_lock:
			if jid:
				jid = str(jid)
				if jid in self.custom_message_handlers:
					del self.custom_message_handlers[jid]
					self.logger.debug('deleting custom message handler for ' + jid)
					return
			if handler_id:
				if not isinstance(handler_id, uuid.UUID):
					handler_id = uuid.UUID(handler_id)
				for jid, handler in self.custom_message_handlers.items():
					if handler['handler_id'] == handler_id:
						del self.custom_message_handlers[jid]
						self.logger.debug('deleting custom message handler for ' + jid)
						return
		if safe:
			self.logger.info('the specified custom message handler does not exist')
			return
		raise Exception('the specified custom message handler does not exist')

	def custom_message_handler_reaper(self):
		with self.custom_message_handler_lock:
			handlers_for_removal = []
			for jid, handler in self.custom_message_handlers.items():
				expiration = handler['expiration']
				if expiration <= datetime.datetime.utcnow():
					handlers_for_removal.append(jid)
			for jid in handlers_for_removal:
				self.custom_message_handler_del(jid=jid)
			if not self.custom_message_handlers:
				self.custom_message_handler_reaper_job_id = None
				return JobRequestDelete()
		return None

	def bot_run(self):
		self.process(block=True)

	def bot_request_stop(self, signum=None, frame=None):
		if signum is None:
			self.logger.warning('received shutdown command, proceeding to stop')
		elif signum == signal.SIGTERM:
			self.logger.warning('received SIGTERM signal, proceeding to stop')
		elif signum == signal.SIGINT:
			self.logger.warning('received SIGINT signal, proceeding to stop')
		elif signum == signal.SIGHUP:
			self.logger.warning('received SIGHUP signal, proceeding to stop')
		self.__shutdown__ = True
		self.disconnect()
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
				if not user.is_admin:
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
			data = stream.read(timeout=5)
		tmp_h.seek(0, 0)
		self.logger.info('done reading AIML archive, bytes read: ' + str(size) + ' SHA-1 checksum: ' + chksum.hexdigest())
		self.aiml_set_update(tmp_h, compression='bz2')
		tmp_h.close()
