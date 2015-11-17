#!/usr/bin/python3 -B
import argparse
import logging
import os
import signal

from cassie.utils import set_proc_name, SectionConfigParser
from cassie.bot.xmpp import CassieXMPPBot
from cassie import __version__

from smoke_zephyr import configuration

def configure_stream_logger(level, logger):
	"""
	Configure the default stream handler for logging messages to the console.
	This also configures the basic logging environment for the application.
	:param level: The level to set the logger to.
	:type level: int, str
	:param str logger: The logger to add the stream handler for.
	:return: The new configured stream handler.
	:rtype: :py:class:`logging.StreamHandler`
	"""
	if isinstance(level, str):
		level = getattr(logging, level)
	root_logger = logging.getLogger('')
	for handler in root_logger.handlers:
		root_logger.removeHandler(handler)

	logging.getLogger(logger).setLevel(logging.DEBUG)
	console_log_handler = logging.StreamHandler()
	console_log_handler.setLevel(level)

	console_log_handler.setFormatter(logging.Formatter("%(levelname)-10s %(message)s"))
	logging.getLogger(logger).addHandler(console_log_handler)
	logging.captureWarnings(True)
	return console_log_handler

def main():
	parser = argparse.ArgumentParser(description='Cassie: Chat Bot For Offensive Security Testing', conflict_handler='resolve')
	parser.add_argument('-c', '--config', dest='config_path', action='store', default='config.yml', help='path to the configuration file')
	parser.add_argument('-f', '--foreground', dest='fork', action='store_false', default=True, help='do not fork a new process')
	parser.add_argument('-v', '--version', action='version', version=parser.prog + ' Version: ' + __version__)
	parser.add_argument('-L', '--log', dest='loglvl', action='store', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='WARNING', help='set the logging level')
	parser.add_argument('--logger', default='cassie', help='specify the root logger')
	arguments = parser.parse_args()

	console_log_handler = configure_stream_logger(arguments.loglvl, arguments.logger)

	config = configuration.Configuration(arguments.config_path)
	settings = {}
	settings['xmpp_jid'] = config.get('xmpp.jid')
	settings['xmpp_password'] = config.get('xmpp.password')
	settings['xmpp_server'] = config.get('xmpp.server')
	settings['xmpp_port'] = config.get('xmpp.port')
	settings['xmpp_admin'] = config.get('xmpp.admin')
	settings['xmpp_users_file'] = config.get('xmpp.users_file')
	if config.has_option('xmpp.chat_room'):
		settings['xmpp_chat_room'] = config.get('xmpp.chat_room')

	# configure logging
	if config.has_section('logging'):
		log_level = min(getattr(logging, arguments.loglvl), getattr(logging, config.get('logging.level').upper()))
		if config.has_option('logging.file') and config.get('logging.file'):
			log_file_path = config.get('logging.file')
			file_handler = logging.FileHandler(log_file_path)
			file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)-45s %(levelname)-10s %(message)s"))
			logging.getLogger('').addHandler(file_handler)
			file_handler.setLevel(log_level)
		if config.has_option('logging.console') and config.get('logging.console'):
			console_log_handler.setLevel(log_level)
	logger = logging.getLogger('cassie.main')

	if not arguments.fork:
		console = logging.StreamHandler()
		console.setFormatter(logging.Formatter("%(levelname)-10s %(message)s"))
		logging.getLogger('').addHandler(console)

	modules = {}
	# try:
	# 	module_sections = filter(lambda x: x[:4] == 'mod_', config.sections())
	# 	for module_name in module_sections:
	# 		module_name = module_name[4:]
	# 		logger.info('loading xmpp module: ' + module_name)
	# 		try:
	# 			module = __import__('cassie.modules.' + module_name, None, None, ['Module'])
	# 			module_instance = module.Module()
	# 		except Exception as err:
	# 			logger.error('loading module: ' + module_name + ' failed with error: ' + err.__class__.__name__)
	# 			continue
	# 		module_instance.config_parser(SectionConfigParser('mod_' + module_name, config))
	# 		modules[module_name] = module_instance
	# except NoOptionError as err:
	# 	print 'Cound Not Validate Option: \'' + err.option + '\' From Config File.'
	# 	return os.EX_CONFIG
	# except ValueError as err:
	# 	print 'Invalid Option ' + err.message + ' From Config File.'
	# 	return os.EX_CONFIG

	if arguments.fork:
		pid_file = config.get('core.pid_file')
		if os.path.isfile(pid_file):
			if not os.access(pid_file, os.W_OK):
				logger.error('insufficient permissions to write to pid file: ' + pid_file)
				return os.EX_NOPERM
		elif not os.access(os.path.split(pid_file)[0], os.W_OK):
			logger.error('insufficient permissions to write to pid file: ' + pid_file)
			return os.EX_NOPERM
		cpid = os.fork()
		if cpid:
			logger.info('forked child process with pid of: ' + str(cpid))
			try:
				with open(pid_file, 'w') as file_h:
					file_h.write(str(cpid) + '\n')
			except IOError:
				logger.error('could not write to pid file: ' + pid_file)
				return os.EX_NOPERM
			return os.EX_OK

	cassie_bot = CassieXMPPBot(
		settings['xmpp_jid'],
		settings['xmpp_password'],
		settings['xmpp_admin'],
		settings['xmpp_users_file'],
		settings.get('xmpp_chat_room')
	)

	if settings.get('core_setuid'):
		if os.getuid() == 0:
			try:
				os.setregid(settings['core_setuid'], settings['core_setuid'])
				os.setreuid(settings['core_setuid'], settings['core_setuid'])
			except:
				logger.critical('could not set the gid and uid to: ' + str(settings['core_setuid']))
				return os.EX_OSERR
			logger.info('successfully set the gid and uid to: ' + str(settings['core_setuid']))
		elif os.getuid() != 0:
			logger.error('cannot setuid when not executed as root')

	if not cassie_bot.connect((settings['xmpp_server'], settings['xmpp_port'])):
		logger.error('connecting to the remote xmpp server failed')
		return os.EX_UNAVAILABLE

	signal.signal(signal.SIGTERM, cassie_bot.bot_request_stop)
	signal.signal(signal.SIGINT, cassie_bot.bot_request_stop)
	signal.signal(signal.SIGHUP, cassie_bot.bot_request_stop)

	cassie_bot.bot_run()
	return os.EX_OK

if __name__ == '__main__':
	set_proc_name('cassie')
	exit(main())
