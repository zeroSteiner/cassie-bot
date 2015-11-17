import logging
import os
import pickle

LVL_ADMIN = 0
LVL_USER = 100
LVL_ROOM = LVL_USER
LVL_GUEST = 1000

class User(object):
	__slots__ = ('level', 'name')
	type = 'user'
	def __init__(self, name, level=LVL_GUEST):
		self.name = name
		self.level = level

	def is_admin(self):
		return self.level == LVL_ADMIN

	def is_user(self):
		return self.level <= LVL_USER

	def is_guest(self):
		return self.level >= LVL_GUEST

	@property
	def level_name(self):
		return get_level_name(self.level)

class Room(User):
	type = 'room'
	def __init__(self, name, level=LVL_ROOM):
		super(Room, self).__init__(name, level)

class UserManager(object):
	__slots__ = ('_users', 'filename', 'logger')
	def __init__(self, filename):
		self.logger = logging.getLogger('cassie.bot.user_manager')
		self.filename = os.path.abspath(filename)
		self._users = {}
		if os.path.isfile(self.filename):
			with open(self.filename, 'rb') as file_h:
				self._users = pickle.load(file_h)
			self.logger.info("successfully loaded {0:,} authorized users".format(len(self._users)))
		else:
			self.logger.warning('starting with empty authorized users because no file found')

	def __contains__(self, item):
		return item in self._users

	def __delitem__(self, item):
		del self._users[item]

	def __getitem__(self, item):
		return self._users[item]

	def __setitem__(self, item, value):
		self._users[item] = value

	def __iter__(self):
		return iter(self._users.values())

	def __len__(self):
		return len(self._users)

	def get(self, item, default=None):
		return self._users.get(item, default)

	def save(self):
		with open(self.filename, 'wb') as file_h:
			pickle.dump(dict((u, ud) for u, ud in self._users.items() if ud.type == 'user'), file_h)

def get_level_by_name(name):
	name = name.strip()
	name = name.lower()
	levels = {'admin': LVL_ADMIN, 'guest': LVL_GUEST, 'user': LVL_USER}
	return levels.get(name)

def get_level_name(level):
	if level == LVL_ADMIN:
		return 'admin'
	elif level == LVL_GUEST:
		return 'guest'
	elif level == LVL_USER:
		return 'user'
	return None
