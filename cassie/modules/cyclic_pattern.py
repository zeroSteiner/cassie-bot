from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

# some clients don't like large messages
MAX_PATTERN_SIZE = 4096

def createCyclicPattern(size):
	char1 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	char2 = "abcdefghijklmnopqrstuvwxyz"
	char3 = "0123456789"

	charcnt = 0
	pattern = ""
	max = int(size)
	while charcnt < max:
		for ch1 in char1:
			for ch2 in char2:
				for ch3 in char3:
					if charcnt < max:
						pattern = pattern + ch1
						charcnt = charcnt + 1
					if charcnt < max:
						pattern = pattern + ch2
						charcnt = charcnt + 1
					if charcnt < max:
						pattern = pattern + ch3
						charcnt = charcnt + 1
	return pattern

class Module(CassieXMPPBotModule):
	def cmd_cyclic_pattern(bot, args):
		parser = ArgumentParserLite('cyclic_pattern', 'create and search a cyclic pattern')
		parser.add_argument('-s', '--size', dest = 'size', type = int, required = True, help = 'pattern size to create')
		parser.add_argument('-p', '--pattern', dest = 'pattern', help = 'pattern to find')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()
		if not bool(len(filter(lambda x: x != None, results))):
			return parser.format_help()

		size = results['size']
		if size > MAX_PATTERN_SIZE:
			return 'size is too large, max is ' + str(MAX_PATTERN_SIZE)
		pattern = createCyclicPattern(size)
		if results['pattern'] == None:
			return pattern
		search_pattern = results['pattern']
		if len(search_pattern) == 8:
			search_pattern = search_pattern.decode('hex')
			search_pattern = list(search_pattern)
			search_pattern.reverse()
			search_pattern = ''.join(search_pattern)
		if len(search_pattern) != 4:
			return 'the search pattern is invalid'
		index = pattern.find(search_pattern)
		if index == -1:
			return 'could not find the search pattern'
		return 'found exact match at ' + str(index)
