import os
import pty
import select
import subprocess

from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

"""
# Example config:
[mod_frotz]
save_directory: /path/to/save/games
binary: /usr/local/bin/dfrotz
game: /path/to/game/file
handler_timeout: 300
"""

def is_read_ready(o, timeout):
	return len(select.select([o], [], [], timeout)[0]) == 1

def is_write_ready(i, timeout):
	return len(select.select([], [i], [], timeout)[1]) == 1

class Frotz(object):
	frotz_flags = ['-p']
	def __init__(self, game_file, frotz_bin = 'dfrotz', read_timeout = 0.5):
		self.read_timeout = read_timeout
		if not os.access(game_file, os.R_OK):
			raise Exception('invalid game file')
		frotz_out_pty = pty.openpty()
		command = [frotz_bin]
		command.extend(self.frotz_flags)
		command.append(game_file)
		self.frotz_proc = subprocess.Popen(command, stdin = subprocess.PIPE, stdout = frotz_out_pty[1], stderr = subprocess.PIPE, bufsize = 1)
		self.frotz_stdin = self.frotz_proc.stdin
		self.frotz_stdout = os.fdopen(frotz_out_pty[0], 'rb', 0)

	def read_output(self):
		output_line = []
		while is_read_ready(self.frotz_stdout, self.read_timeout):
			output_line.append(self.frotz_stdout.readline())
		return ''.join(output_line)

	def start_game(self, restore_file = None):
		output = self.read_output()
		if restore_file:
			self.frotz_stdin.write('restore\n')
			self.frotz_stdin.flush()
			self.frotz_stdin.write(restore_file + '\n')
			self.frotz_stdin.flush()
			output = self.read_output()
		if output.startswith('> '):
			output = output[2:]
		return output

	def interpret(self, command):
		command = command.strip()
		self.frotz_stdout.flush()
		self.frotz_stdin.write(command + '\n')
		self.frotz_stdin.flush()
		output = self.read_output()
		if output.startswith('> '):
			output = output[2:]
		return output

	def end_game(self):
		self.frotz_proc.kill()

	@property
	def running(self):
		return self.frotz_proc.poll() == None

class Module(CassieXMPPBotModule):
	def __init__(self):
		CassieXMPPBotModule.__init__(self)
		self.frotz_instances = {}

	def cmd_frotz(self, args, jid):
		parser = ArgumentParserLite('frotz', 'play games with frotz')
		parser.add_argument('--new', dest = 'new_game', action = 'store_true', help = 'start a new game')
		parser.add_argument('--quit', dest = 'quit_game', action = 'store_true', help = 'quit playing the game')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()

		user = str(jid.bare)
		save_file_name = os.path.join(self.options['save_directory'], user + '.frotz')

		if results['new_game']:
			self.logger.info(str(jid.jid) + ' is starting a new game with frotz')
			self.frotz_instances[user] = Frotz(self.options['game'], frotz_bin = self.options['binary'])
			frotz = self.frotz_instances[user]
			self.bot.custom_message_handler_add(jid, self.callback_play_game, self.options['handler_timeout'])
			return frotz.start_game()
		
		if not user in self.frotz_instances:
			return 'Frotz is not currently running'
		frotz = self.frotz_instances[user]

		if results['quit_game']:
			if frotz.running:
				frotz.end_game()
			del self.frotz_instances[user]
			self.bot.custom_message_handler_del(jid)
			return 'Ended Frotz game, thanks for playing'

	def callback_play_game(self, msg, jid):
		user = str(jid.bare)
		save_file_name = os.path.join(self.options['save_directory'], user + '.frotz')
		if not user in self.frotz_instances:
			self.logger.error('callback_play_game executed but user has no Frotz instance')
			return 'Not currently playing a game'
		frotz = self.frotz_instances[user]
		msg = msg.strip()
		if not msg:
			return
		cmd = msg.split(' ', 1)[0]
		if cmd in ['save', 'restore', 'q', 'quit']:
			return
		self.bot.custom_message_handler_add(jid, self.callback_play_game, self.options['handler_timeout'])
		return frotz.interpret(msg)

	def config_parser(self, config):
		self.options['save_directory'] = config.get('save_directory')
		self.options['binary'] = config.get('binary', 'dfrotz')
		self.options['game'] = config.get('game')
		self.options['handler_timeout'] = config.getint('handler_timeout', 300)
		return self.options
