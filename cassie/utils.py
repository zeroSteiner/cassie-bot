def set_proc_name(newname):
	from ctypes import cdll, byref, create_string_buffer
	try:
		libc = cdll.LoadLibrary('libc.so.6')
		buff = create_string_buffer(len(newname) + 1)
		buff.value = newname
		libc.prctl(15, byref(buff), 0, 0, 0)
	except:
		return False
	return True

def generate_progress_bar(part, total = None, percision = 4, number_of_bars = 40):
	bar_template = "{0:>" + str(5 + percision) + "} [{1:<" + str(number_of_bars) + "}]"
	if total == None:
		percent = (float(part) / 100.0)
	else:
		percent = (float(part) / float(total))
	bars = int(number_of_bars * percent)
	progress_bar = bar_template.format(format(percent, '.' + str(percision) + '%'), ('=' * bars))
	return progress_bar

class SectionConfigParser:
	__version__ = '0.1'
	def __init__(self, section_name, config_parser):
		self.section_name = section_name
		self.config_parser = config_parser

	def get_raw(self, option, opt_type, default = None):
		get_func = getattr(self.config_parser, 'get' + opt_type)
		if default == None:
			return get_func(self.section_name, option)
		elif self.config_parser.has_option(self.section_name, option):
			return get_func(self.section_name, option)
		else:
			return default

	def get(self, option, default = None):
		return self.get_raw(option, '', default)

	def getint(self, option, default = None):
		return self.get_raw(option, 'int', default)

	def getfloat(self, option, default = None):
		return self.get_raw(option, 'float', default)

	def getboolean(self, option, default = None):
		return self.get_raw(option, 'boolean', default)

	def has_option(self, option):
		return self.config_parser.has_option(self.section_name, option)

	def options(self):
		return self.config_parser.options(self.section_name)

	def items(self):
		self.config_parser.items(self.section_name)
