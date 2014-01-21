import copy
import textwrap

from cassie.errors import CassieCommandError

MAX_WIDTH = 60
MAX_ARG_WIDTH = 24

class ArgumentParserLite:
	def __init__(self, prog = '', description = None, epilog = None):
		self.prog = prog
		self.description = '\n'.join(textwrap.wrap((description or ''), MAX_WIDTH))
		self.epilog = '\n'.join(textwrap.wrap((epilog or ''), MAX_WIDTH))
		self.__arguments__ = {}
		self.__positionals__ = []
		self.ignore_urls = True

	def format_usage(self):
		self_arguments = copy.deepcopy(self.__arguments__)
		usage = 'usage: ' + self.prog
		args = self_arguments.keys()
		args = filter(lambda arg: arg.startswith('-'), args)
		args.sort()
		args.extend(self.__positionals__)
		for arg in args:
			if not arg in self_arguments:
				continue
			arg_desc = self_arguments[arg]
			if len(usage.split('\n')[-1]) > MAX_WIDTH:
				usage += '\n' + (' ' * len('usage: ' + self.prog))
			if arg_desc['action'] != 'store':
				usage += ' [' + arg + ']'
			elif arg_desc['dest'] == arg:
				usage += ' [' + arg.upper() + ']'
			else:
				usage += ' [' + arg + ' ' + arg_desc['dest'].upper() + ']'
			for arg in arg_desc['__aliases__']:
				del self_arguments[arg]
		return usage

	def format_help(self):
		self_arguments = copy.deepcopy(self.__arguments__)
		help_text = self.format_usage() + '\n\n'
		if self.description:
			help_text += self.description + '\n\n'
		help_text += 'arguments:\n'
		args = self_arguments.keys()
		args = filter(lambda arg: arg.startswith('-'), args)
		args.sort()
		args.extend(self.__positionals__)
		for arg in args:
			if not arg in self_arguments:
				continue
			arg_desc = self_arguments[arg]
			arg_string = ' ' + ', '.join(arg_desc['__aliases__'])
			if arg_desc['action'] == 'store':
				arg_string += ' ' + arg_desc['dest'].upper()
			arg_string += ' '
			if len(arg_string) > MAX_ARG_WIDTH:
				help_text += arg_string + '\n'
				arg_string = (' ' * MAX_ARG_WIDTH)
			else:
				arg_string += (' ' * (MAX_ARG_WIDTH - len(arg_string)))
			help_words = arg_desc['help'].split()

			while len(help_words):
				word = help_words.pop(0)
				while (len(arg_string) < MAX_WIDTH) and len(help_words):
					arg_string += word + ' '
					word = help_words.pop(0)
				if len(help_words):
					arg_string += '\n'
			arg_string += word + ' ' + '\n'
			help_text += arg_string
			for arg in arg_desc['__aliases__']:
				del self_arguments[arg]
		if self.epilog:
			help_text += '\n' + self.epilog
		return help_text

	def parse_args(self, args, raise_exception = True):
		already_done = []
		last_argument = None
		self_arguments = copy.deepcopy(self.__arguments__)
		results = {}
		for arg in args:
			if last_argument == None and not arg in self_arguments:
				if arg in ['-h', '--help']:
					raise CassieCommandError(self.format_help())
				arg = str(arg)
				if self.ignore_urls and arg.startswith('<http') and arg.endswith('>'):
					continue
				if len(self.__positionals__) == 0:
					raise CassieCommandError('error: unrecognized argument: ' + arg)
				last_argument = self.__positionals__.pop(0)
			if last_argument:
				arg_desc = self_arguments[last_argument]
				try:
					results[arg_desc['dest']] = arg_desc['type'](arg)
				except:
					raise CassieCommandError('error: argument ' + str(last_argument) + ': invalid ' + repr(arg_desc['type'])[7:-2] + ' value: \'' + arg + '\'')
				last_argument = None
				continue
			else:
				arg_desc = self_arguments[arg]
			if arg_desc['action'] == 'store_true':
				results[arg_desc['dest']] = True
			elif arg_desc['action'] == 'store_false':
				results[arg_desc['dest']] = False
			else:
				last_argument = arg
			already_done.append(arg)
		if last_argument:
			raise CassieCommandError('error: argument ' + last_argument + ': expected one argument')

		for arg in already_done:
			del self_arguments[arg]
		for arg, arg_desc in self_arguments.items():
			if arg_desc['dest'] in results:
				continue
			if arg_desc['required']:
				raise CassieCommandError('error: missing argument: ' + str(arg))
			else:
				results[arg_desc['dest']] = arg_desc['default']
		return results

	def add_argument(self, *args, **kwargs):
		if not 'action' in kwargs: kwargs['action'] = 'store'
		if not 'default' in kwargs: kwargs['default'] = None
		if not 'required' in kwargs: kwargs['required'] = False
		if not 'help' in kwargs: kwargs['help'] = ''
		if not 'type' in kwargs: kwargs['type'] = str
		kwargs['__aliases__'] = args

		# defaults have been set, now sanitize
		if len(args) == 1 and not args[0].startswith('-'):
			name = args[0]
			if name in self.__positionals__:
				raise ValueError('duplicate positional argument')
			if not kwargs['required']:
				raise ValueError('positional arguments must be required')
			if 'dest' in kwargs:
				raise Exception('dest can not be specified for positional arguments')
			kwargs['dest'] = name
			self.__positionals__.append(name)
		else:
			if not 'dest' in kwargs: raise Exception('dest must be defined')
			for name in args:
				if not ((len(name) == 2) and name[0] == '-') and not ((len(name) > 2) and (name[0:2] == '--')):
					raise ValueError('arguments must be formated as -x or --xxx')

		if kwargs['action'] not in ['store', 'store_true', 'store_false']:
			raise ValueError('invalid action: ' + kwargs['action'])
		if not type(kwargs['type']) == type:
			raise ValueError('invalid type: ' + str(kwargs['type']))
		for name in args:
			self.__arguments__[name] = kwargs
