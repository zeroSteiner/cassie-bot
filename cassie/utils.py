def set_proc_name(newname):
	from ctypes import cdll, byref, create_string_buffer
	try:
		libc = cdll.LoadLibrary('libc.so.6')
		buff = create_string_buffer(len(newname) + 1)
		buff.value = newname
		libc.prctl(15, byref(buff), 0, 0, 0)
	except Exception:
		return False
	return True

def generate_progress_bar(part, total=None, percision=4, number_of_bars=40):
	bar_template = "{0:>" + str(5 + percision) + "} [{1:<" + str(number_of_bars) + "}]"
	if total is None:
		percent = (float(part) / 100.0)
	else:
		percent = (float(part) / float(total))
	bars = int(number_of_bars * percent)
	progress_bar = bar_template.format(format(percent, '.' + str(percision) + '%'), ('=' * bars))
	return progress_bar

