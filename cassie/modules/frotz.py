import os
import pty
import select
import termios
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
	def __init__(self, game_file, frotz_bin = 'dfrotz', read_timeout = 0.25):
		self.read_timeout = read_timeout
		if not os.access(game_file, os.R_OK):
			raise Exception('invalid game file')
		command = [frotz_bin]
		command.extend(self.frotz_flags)
		command.append(game_file)

		frotz_out_pty = pty.openpty()
		# disable echoing input
		settings = termios.tcgetattr(frotz_out_pty[0])
		settings[3] = settings[3] & ~termios.ECHO
		termios.tcsetattr(frotz_out_pty[0], termios.TCSADRAIN, settings)
		
		self.frotz_proc = subprocess.Popen(command, stdin = frotz_out_pty[1], stdout = frotz_out_pty[1], stderr = subprocess.PIPE, bufsize = 0)
		self.frotz_stdin = os.fdopen(frotz_out_pty[0], 'wrb', 0)
		self.frotz_stdout = self.frotz_stdin

	def read_output(self):
		output_line = []
		while is_read_ready(self.frotz_stdout, self.read_timeout):
			output_line.append(self.frotz_stdout.read(1))
		output = ''.join(output_line)
		if output.endswith('>'):
			output = output[:-1]
		output = output.strip()
		return output

	def restore_game(self, restore_file):
		self.frotz_stdin.write('restore\n')
		if is_read_ready(self.frotz_stdout, self.read_timeout):
			termios.tcflush(self.frotz_stdout, termios.TCIFLUSH)
		self.frotz_stdin.write(restore_file + '\n')
		output = self.read_output()
		return output

	def start_game(self, restore_file = None):
		output = self.read_output()
		if restore_file:
			output = self.restore_game(restore_file)
		return output

	def save_game(self, save_file):
		self.frotz_stdin.write('save\n')
		if is_read_ready(self.frotz_stdout, self.read_timeout):
			termios.tcflush(self.frotz_stdout, termios.TCIFLUSH)
		self.frotz_stdin.write(save_file + '\n')
		output = self.read_output()
		if output.lower().startswith('overwrite existing file?'):
			self.frotz_stdin.write('Y\n')
			output = self.read_output()
		return output

	def interpret(self, command):
		command = command.strip()
		self.frotz_stdin.write(command + '\n')
		output = self.read_output()
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
		parser.add_argument('-n', '--new', dest = 'new_game', action = 'store_true', help = 'start a new game')
		parser.add_argument('-q', '--quit', dest = 'quit_game', action = 'store_true', help = 'quit playing the game')
		parser.add_argument('-s', '--save', dest = 'save_game', action = 'store_true', help = 'save the current game')
		parser.add_argument('-r', '--restore', dest = 'restore_game', action = 'store_true', help = 'restore a previous game')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()

		user = str(jid.bare)
		game_file = self.options['game']
		save_file_name = user.replace('@', '_at_') + '.' + os.path.splitext(os.path.basename(game_file))[0] + '.qzl'
		save_file_path = os.path.join(self.options['save_directory'], save_file_name)

		if results['new_game'] or results['restore_game']:
			if results['new_game']:
				self.logger.info(str(jid.jid) + ' is starting a new game with frotz')
			elif results['restore_game']:
				self.logger.info(str(jid.jid) + ' is restoring a game with frotz')
			self.frotz_instances[user] = Frotz(game_file, frotz_bin = self.options['binary'])
			frotz = self.frotz_instances[user]
			self.bot.custom_message_handler_add(jid, self.callback_play_game, self.options['handler_timeout'])
			output = frotz.start_game()
			if results['restore_game']:
				output = frotz.restore_game(save_file_path)
			return output
		
		if not user in self.frotz_instances:
			return 'Frotz is not currently running'
		frotz = self.frotz_instances[user]
		if not frotz.running:
			return 'Frotz is not currently running'
			del self.frotz_instances[user]
			self.bot.custom_message_handler_del(jid)

		if results['save_game']:
			self.logger.debug(str(jid.jid) + ' is saving a game with frotz')
			return frotz.save_game(save_file_path)

		if results['quit_game']:
			self.logger.debug(str(jid.jid) + ' is quitting a game with frotz')
			frotz.end_game()
			del self.frotz_instances[user]
			self.bot.custom_message_handler_del(jid)
			return 'Ended Frotz game, thanks for playing'

	def callback_play_game(self, msg, jid):
		user = str(jid.bare)

		if not user in self.frotz_instances:
			self.logger.error('callback_play_game executed but user has no Frotz instance')
			return 'Not currently playing a game'
		frotz = self.frotz_instances[user]
		msg = msg.strip()
		if not msg:
			return
		cmd = msg.split(' ', 1)[0]
		if cmd.lower() in ['new', 'save', 'restore', 'q', 'quit']: # command to arguments ie new to -n and save to -s
			cmd = cmd.lower()
			return self.cmd_frotz(['-' + cmd[0]], jid)
		self.bot.custom_message_handler_add(jid, self.callback_play_game, self.options['handler_timeout'])
		return frotz.interpret(msg)

	def config_parser(self, config):
		self.options['save_directory'] = config.get('save_directory')
		self.options['binary'] = config.get('binary', 'dfrotz')
		self.options['game'] = config.get('game')
		self.options['handler_timeout'] = config.getint('handler_timeout', 600)
		return self.options
