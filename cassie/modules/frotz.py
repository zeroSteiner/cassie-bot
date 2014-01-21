import os
import pty
import select
import termios
import threading
import subprocess

from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

"""
# Example config:
[mod_frotz]
save_directory: /path/to/save/games
binary: /usr/local/bin/dfrotz
handler_timeout: 300
# Games are listed here
game0: Game0,/path/to/game/file
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
		self.frotz_game_file = game_file

	def read_output(self):
		output_line = []
		while is_read_ready(self.frotz_stdout, self.read_timeout):
			output_line.append(self.frotz_stdout.read(1))
		output = ''.join(output_line)
		if output.endswith('>'):
			output = output[:-1]
		output = output.strip()
		return output

	def game_restore(self, restore_file):
		self.frotz_stdin.write('restore\n')
		if is_read_ready(self.frotz_stdout, self.read_timeout):
			termios.tcflush(self.frotz_stdout, termios.TCIFLUSH)
		self.frotz_stdin.write(restore_file + '\n')
		output = self.read_output()
		return output

	def game_start(self, restore_file = None):
		output = self.read_output()
		if restore_file:
			output = self.game_restore(restore_file)
		return output

	def game_save(self, save_file):
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

	def game_end(self):
		if not self.running:
			return
		self.frotz_proc.kill()
		self.frotz_proc.wait()

	@property
	def running(self):
		return self.frotz_proc.poll() == None

class Module(CassieXMPPBotModule):
	def __init__(self):
		CassieXMPPBotModule.__init__(self)
		self.frotz_instances = {}
		self.frotz_instances_lock = threading.RLock()

	def init_bot(self, *args, **kwargs):
		CassieXMPPBotModule.init_bot(self, *args, **kwargs)
		self.bot.command_handler_set_permission('frotz', 'user')
		self.job_id = self.bot.job_manager.job_add(self.game_reaper, hours = 0, minutes = 5, seconds = 0)

	def cmd_frotz(self, args, jid, is_muc):
		parser = ArgumentParserLite('frotz', 'play z-machine games with frotz', 'each user can create one save file per game')
		parser.add_argument('-n', '--new', dest = 'new_game', action = 'store_true', help = 'start a new game')
		parser.add_argument('-r', '--restore', dest = 'restore_game', action = 'store_true', help = 'restore a previous game')
		parser.add_argument('-q', '--quit', dest = 'quit_game', action = 'store_true', help = 'quit playing the game')
		parser.add_argument('-s', '--save', dest = 'save_game', action = 'store_true', help = 'save the current game')
		parser.add_argument('-g', '--game', dest = 'game', action = 'store', help = 'game to play')
		parser.add_argument('--list-games', dest = 'list_games', action = 'store_true', help = 'list available games')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		user = str(jid.bare)

		if results['list_games']:
			resp = ['Available Games:']
			games = self.options['games'].keys()
			games.sort()
			resp.extend(games)
			return resp

		with self.frotz_instances_lock:
			if results['new_game'] or results['restore_game']:
				if not results['game'] in self.options['games']:
					if results['game'] == None:
						msg = 'Please select a game with the -g option'
					else:
						msg = 'Invalid game file'
					return msg + ', use --list-games to show available games'
				game_file = self.options['games'][results['game']]
			elif results['save_game'] or results['quit_game']:
				if results['game']:
					return 'Can\'t select a game with --save or --quit'
				if not user in self.frotz_instances:
					return 'Frotz is not currently running'
				frotz = self.frotz_instances[user]['frotz']
				if not frotz.running:
					self.cleanup_game(user)
					return 'Frotz is not currently running'
				game_file = frotz.frotz_game_file

			save_file_name = user.replace('@', '_at_') + '.' + os.path.splitext(os.path.basename(game_file))[0] + '.qzl'
			save_file_path = os.path.join(self.options['save_directory'], save_file_name)

			if results['new_game'] or results['restore_game']:
				if user in self.frotz_instances:
					self.cleanup_game(user)
				if results['new_game']:
					self.logger.info(str(jid.jid) + ' is starting a new game with frotz')
				elif results['restore_game']:
					self.logger.info(str(jid.jid) + ' is restoring a game with frotz')
				self.frotz_instances[user] = {'frotz':Frotz(game_file, frotz_bin = self.options['binary']), 'handler_id':None}
				frotz = self.frotz_instances[user]['frotz']
				if is_muc:
					handler_id = self.bot.custom_message_handler_add(jid.bare, self.callback_play_game, self.options['handler_timeout'])
				else:
					handler_id = self.bot.custom_message_handler_add(jid, self.callback_play_game, self.options['handler_timeout'])
				self.frotz_instances[user]['handler_id'] = handler_id
				output = frotz.game_start()
				if results['restore_game']:
					output = frotz.game_restore(save_file_path)
				return output

			if results['save_game']:
				self.logger.debug(str(jid.jid) + ' is saving a game with frotz')
				return frotz.game_save(save_file_path)

			if results['quit_game']:
				self.logger.debug(str(jid.jid) + ' is quitting a game with frotz')
				self.cleanup_game(user)
				return 'Ended Frotz game, thanks for playing'

	def cleanup_game(self, user):
		with self.frotz_instances_lock:
			game_info = self.frotz_instances[user]
			game_info['frotz'].game_end()
			self.bot.custom_message_handler_del(handler_id = game_info['handler_id'], safe = True)
			del self.frotz_instances[user]

	def game_reaper(self):
		with self.frotz_instances_lock:
			games_for_removal = []
			for user, game_info in self.frotz_instances.items():
				if not self.bot.custom_message_handler_exists(handler_id = game_info['handler_id']):
					games_for_removal.append(user)
			for user in games_for_removal:
				self.cleanup_game(user)

	def callback_play_game(self, msg, jid, handler_id):
		user = str(jid.bare)
		frotz = self.frotz_instances[user]['frotz']
		msg = msg.strip()
		if not msg:
			return
		cmd = msg.split(' ', 1)[0]
		if cmd.lower() in ['new', 'restore', 'save', 'q', 'quit']:	# command to arguments ie new to --new and save to --save
			cmd = cmd.lower()
			if len(cmd) == 1:
				args = ['-' + cmd[0]]
			else:
				args = ['--' + cmd]
			if cmd in ['new', 'restore']:	# new and restore require a game to be specified
				game = None
				for game_name, game_file in self.options['games'].items():
					if game_file == frotz.frotz_game_file:
						game = game_name
				if not game:
					raise Exception('could not determine the current game name')
				args.append('-g')
				args.append(game)
			return self.cmd_frotz(args, jid)
		return frotz.interpret(msg)

	def config_parser(self, config):
		self.options['save_directory'] = config.get('save_directory')
		self.options['binary'] = config.get('binary', 'dfrotz')
		self.options['handler_timeout'] = config.getint('handler_timeout', 600)
		self.options['games'] = {}
		for opt_name, opt_value in config.items():
			if not opt_name.startswith('game'):
				continue
			game_name, game_file = opt_value.split(',', 1)
			game_name = game_name.strip()
			game_file = game_file.strip()
			self.options['games'][game_name] = game_file
		self.logger.debug('loaded ' + str(len(self.options['games'])) + ' zmachine games')
		return self.options
