#!/usr/bin/python -B
import os
import sys
import signal
import logging
import getpass
from argparse import ArgumentParser
from ConfigParser import ConfigParser, NoOptionError
from cassie.utils import set_proc_name, SectionConfigParser
from cassie.bot.xmpp import CassieXMPPBot, CassieXMPPBotAimlUpdater
from cassie.bot.tcp import CassieTCPBot
from cassie import __version__

PROMPT = 'cassie > '

# Python versions before 3.0 do not use UTF-8 encoding
# by default. To ensure that Unicode is handled properly
# throughout SleekXMPP, we will set the default encoding
# ourselves to UTF-8.
if sys.version_info < (3, 0):
	reload(sys)
	sys.setdefaultencoding('utf8')
else:
	raw_input = input

def main():
	parser = ArgumentParser(description = 'Cassie: Chat Bot For Offensive Security Testing', conflict_handler='resolve')
	parser.add_argument('-c', '--config', dest = 'config_path', action = 'store', default = 'cassie.conf', help = 'path to the config file')
	parser.add_argument('-f', '--foreground', dest = 'fork', action = 'store_false', default = True, help = 'run in foreground/do not fork a new process')
	parser.add_argument('-u', '--update', dest = 'update', action = 'store_true', default = False, help = 'log in and update the currently loaded AIML set')
	parser.add_argument('-l', '--local', dest = 'local', action = 'store_true', default = False, help = 'start a local AIML interpreter prompt')
	parser.add_argument('-v', '--version', action = 'version', version = parser.prog + ' Version: ' + __version__)
	parser.add_argument('-L', '--log', dest = 'loglvl', action = 'store', choices = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default = 'WARNING', help = 'set the logging level') 
	arguments = parser.parse_args()
	
	config = ConfigParser()
	config.read(arguments.config_path)
	settings = {}
	try:
		settings['core_log_file'] = config.get('core', 'log_file')
		if config.has_option('core', 'setuid'):
			settings['core_setuid'] = config.getint('core', 'setuid')
		pid_file = config.get('core', 'pid_file')
		settings['core_mode'] = config.get('core', 'mode').lower()
		settings['aiml_path'] = config.get('aiml', 'path')
		settings['aiml_botmaster'] = config.get('aiml', 'botmaster')
		
		if config.has_section('xmpp'):
			settings['xmpp_jid'] = config.get('xmpp', 'jid')
			settings['xmpp_password'] = config.get('xmpp', 'password')
			settings['xmpp_server'] = config.get('xmpp', 'server')
			settings['xmpp_port'] = config.getint('xmpp', 'port')
			settings['xmpp_admin'] = config.get('xmpp', 'admin')
			settings['xmpp_users_file'] = config.get('xmpp', 'users_file')
			if config.has_option('xmpp', 'chat_room'):
				settings['xmpp_chat_room'] = config.get('xmpp', 'chat_room')
		
		if config.has_section('tcpserver'):
			settings['tcpsrv_server'] = config.get('tcpserver', 'server')
			settings['tcpsrv_port'] = config.getint('tcpserver', 'port')
		
	except NoOptionError as err:
		print 'Cound Not Validate Option: \'' + err.option + '\' From Config File.'
		return os.EX_CONFIG
	except ValueError as err:
		print 'Invalid Option ' + err.message + ' From Config File.'
		return os.EX_CONFIG

	# configure logging
	logging.basicConfig(filename = settings['core_log_file'], level = getattr(logging, arguments.loglvl), format = "%(name)s\t %(levelname)-10s %(asctime)s %(message)s")
	logger = logging.getLogger('cassie.main')

	if settings['core_mode'] == 'xmpp':
		modules = {}
		try:
			module_sections = filter(lambda x: x[:4] == 'mod_', config.sections())
			for module_name in module_sections:
				module_name = module_name[4:]
				logger.info('loading module: ' + module_name)
				try:
					module = __import__('cassie.modules.' + module_name, None, None, ['Module'])
					module_instance = module.Module()
				except Exception as err:
					logger.error('failed to load module: ' + module_name)
					continue
				module_instance.config_parser(SectionConfigParser('mod_' + module_name, config))
				modules[module_name] = module_instance
		except NoOptionError as err:
			print 'Cound Not Validate Option: \'' + err.option + '\' From Config File.'
			return os.EX_CONFIG
		except ValueError as err:
			print 'Invalid Option ' + err.message + ' From Config File.'
			return os.EX_CONFIG
	
	if arguments.local or not arguments.fork or arguments.update:
		console = logging.StreamHandler()
		console.setFormatter(logging.Formatter("%(levelname)-10s: %(message)s"))
		logging.getLogger('').addHandler(console)
	
	if arguments.local:
		from cassie.brain import Brain
		cassie = Brain(modules)
		cassie.setBotPredicate('name', 'Cassie')
		cassie.setBotPredicate('botmaster', settings['aiml_botmaster'])
		cassie.setBotPredicate('client-name', 'localuser')
		cassie.setBotPredicate('client-name-full', 'localuser@localhost')
		for root, dirs, files in os.walk(settings['aiml_path']):
			for name in files:
				if os.path.join(root, name).endswith('.aiml'):
					cassie.learn(os.path.join(root, name))
		logger.info("the AIML kernel contains {:,} categories".format(cassie.numCategories()))
		print 'Hit Ctrl+C When You\'re Done.'
		try:
			while True:
				print cassie.respond(raw_input(PROMPT))
		except KeyboardInterrupt:
			pass
		except EOFError:
			pass
		print ''
		return os.EX_OK
	
	if arguments.update:
		print 'Authenticating as: ' + settings['xmpp_admin']
		try:
			password = getpass.getpass("Password: ")
		except KeyboardInterrupt:
			return os.EX_OK
		xmpp = CassieXMPPBotAimlUpdater(settings['xmpp_admin'], password, settings['xmpp_jid'], settings['aiml_path'])
		logging.info('connecting to the server to initiate an AIML update')
		if xmpp.connect((settings['xmpp_server'], settings['xmpp_port'])):
			logging.info('transfering the AIML archive')
			xmpp.process(block = True)
		return os.EX_OK
	
	if arguments.fork:
		if os.path.isfile(pid_file):
			if not os.access(pid_file, os.W_OK):
				logger.error('insufficient permissions to write to PID file: ' + pid_file)
				return os.EX_NOPERM
		elif not os.access(os.path.split(pid_file)[0], os.W_OK):
			logger.error('insufficient permissions to write to PID file: ' + pid_file)
			return os.EX_NOPERM
		cpid = os.fork()
		if cpid:
			logger.info('forked child process with PID of: ' + str(cpid))
			try:
				pid_file_h = open(pid_file, 'w')
				pid_file_h.write(str(cpid) + '\n')
			except IOError:
				logger.error('could not write to PID file: ' + pid_file)
			return os.EX_OK

	if settings['core_mode'] == 'xmpp':
		xmpp = CassieXMPPBot(
			settings['xmpp_jid'],
			settings['xmpp_password'],
			settings['xmpp_admin'],
			settings['xmpp_users_file'],
			settings['aiml_path'],
			settings['aiml_botmaster'],
			modules
		)
	if settings.get('core_setuid'):
		if os.getuid() == 0:
			try:
				os.setregid(settings['core_setuid'], settings['core_setuid'])
				os.setreuid(settings['core_setuid'], settings['core_setuid'])
			except:
				logger.critical('could not set the gid and uid to: ' + str(settings['core_setuid']))
				return os.EX_OK
			logger.info('successfully set the gid and uid to: ' + str(settings['core_setuid']))
		elif os.getuid() != 0:
			logger.error('cannot setuid when not executed as root')
	
	if settings['core_mode'] == 'xmpp':
		signal.signal(signal.SIGTERM, xmpp.request_stop)
		signal.signal(signal.SIGINT, xmpp.request_stop)
		signal.signal(signal.SIGHUP, xmpp.request_stop)
		if xmpp.connect((settings['xmpp_server'], settings['xmpp_port'])):
			if settings.get('xmpp_chat_room'):
				xmpp.join_chat_room(settings['xmpp_chat_room'])
			xmpp.process(block = True)
	if settings['core_mode'] == 'tcpserver':
		server_address = (settings['tcpsrv_server'], settings['tcpsrv_port'])
		tcpserver = CassieTCPBot(server_address, settings['aiml_path'], settings['aiml_botmaster'], PROMPT)
		tcpserver.serve_forever()
	return os.EX_OK

if __name__ == '__main__':
	set_proc_name('cassie')
	exit(main())
