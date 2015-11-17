import logging
import os
import time

from cassie import __version__
from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

class Module(CassieXMPPBotModule):
	def cmd_bot(self, args, jid, is_muc):
		parser = ArgumentParserLite('bot', 'control the bot')
		parser.add_argument('-l', '--log', dest='loglvl', action='store', default=None, help='set the bots logging level')
		parser.add_argument('--shutdown', dest='stop', action='store_true', default=False, help='stop the bot from running')
		parser.add_argument('--join', dest='chat_room_join', action='store', default=None, help='join a chat room')
		parser.add_argument('--leave', dest='chat_room_leave', action='store', default=None, help='leave a chat room')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		response = ''
		if results['loglvl']:
			results['loglvl'] = results['loglvl'].upper()
			if results['loglvl'] in ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'):
				log = logging.getLogger('')
				log.setLevel(getattr(logging, results['loglvl']))
				self.logger.info('successfully set the logging level to: ' + results['loglvl'])
				response += 'Successfully set the logging level to: ' + results['loglvl']
			else:
				response += 'Invalid log level: ' + results['loglvl'] + '\n'
		if results['chat_room_join']:
			self.bot.chat_room_join(results['chat_room_join'])
			response += 'Joined chat room: ' + results['chat_room_join'] + '\n'
		if results['chat_room_leave']:
			self.bot.chat_room_leave(results['chat_room_leave'])
			response += 'Left chat room: ' + results['chat_room_leave'] + '\n'
		if results['stop']:
			self.bot.bot_request_stop()
		return response

	def cmd_info(self, args, jid, is_muc):
		records = self.bot.records
		now = int(time.time())
		response = 'Cassie Information:\n'
		response += '== General Information ==\n'
		response += 'Version: ' + __version__ + '\n'
		response += 'PID: ' + str(os.getpid()) + '\n'
		response += "Number of Messages: {:,}\n".format(records['message count'])
		response += "Number of Failed Messages: {:,}\n".format(records['failed message count'])
		if records['message count'] != 0:
			response += "Message Success Rate: {:.2f}%\n".format((float(records['message count'] - records['failed message count']) / float(records['message count'])) * 100)
		response += "Number of Jobs: Enabled: {:,} Total: {:,}\n".format(self.bot.job_manager.job_count_enabled(), self.bot.job_manager.job_count())
		if len(self.bot.bot_modules):
			response += 'Loaded Modules:'
			response += '\n    ' + "\n    ".join(sorted(mod.name for mod in self.bot.bot_modules))
			response += '\n'

		response += '\n== Uptime Information ==\n'
		response += 'Core Initialization Time: ' + time.asctime(time.localtime(records['init time'])) + '\n'
		then = int(records['init time'])
		days = (now - then) / DAY
		hours = ((now - then) % DAY) / HOUR
		minutes = (((now - then) % DAY) % HOUR) / MINUTE
		seconds = (((now - then) % DAY) % HOUR) % MINUTE
		response += "Core Uptime: {:,.0f} days {:.0f} hours {:.0f} minutes {:.0f} seconds\n".format(days, hours, minutes, seconds)

		response += 'Last XMPP Connect Time: ' + time.asctime(time.localtime(records['last connect time'])) + '\n'
		then = int(records['last connect time'])
		days = (now - then) / DAY
		hours = ((now - then) % DAY) / HOUR
		minutes = (((now - then) % DAY) % HOUR) / MINUTE
		seconds = (((now - then) % DAY) % HOUR) % MINUTE
		response += "XMPP Uptime: {:,.0f} days {:.0f} hours {:.0f} minutes {:.0f} seconds\n".format(days, hours, minutes, seconds)
		return response[:-1]
