from urllib import urlencode
import urllib2
import xml.etree.ElementTree as ET

from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

"""
# Example config:
[mod_openfire]
host: 127.0.0.1
port: 9091
use_ssl: true
secret: blahblah
default_groups:
"""

# http://www.igniterealtime.org/projects/openfire/plugins/userservice/readme.html
USER_SERVICE_PATH = '/plugins/userService/userservice'
class Module(CassieXMPPBotModule):
	def get_params(self, reqtype, username):
		params = {}
		params['type'] = reqtype
		params['secret'] = self.options['secret']
		params['username'] = username
		return params

	def process_request(self, params):
		scheme = 'http'
		if self.options['use_ssl']:
			scheme += 's'
		uri = "{scheme}://{host}:{port}{path}?{query}"
		uri = uri.format(scheme = scheme, host = self.options['host'], port = self.options['port'], path = USER_SERVICE_PATH, query = urlencode(params))

		response = urllib2.urlopen(uri).read()
		response = response.strip()
		response = ET.fromstring(response)

		tag = response.tag.lower()
		text = response.text.lower()
		if tag == 'result' and text == 'ok':
			return 'Command completed successfully'
		elif tag == 'error':
			return 'Error \'' + response.text + '\' occurred'
		else:
			return 'An unknown error occurred'

	def cmd_openfire(self, args, jid, is_muc):
		parser = ArgumentParserLite('openfire', 'manager users on openfire')
		parser.add_argument('-a', '--add', dest = 'add_user', default = None, help = 'username to add')
		parser.add_argument('-d', '--del', dest = 'del_user', default = None, help = 'username to delete')
		parser.add_argument('--enable', dest = 'enable_user', default = None, help = 'username to enable')
		parser.add_argument('--disable', dest = 'disable_user', default = None, help = 'username to disable')
		parser.add_argument('-p', '--pass', dest = 'password', default = None, help = 'password for the new user')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		response = ''
		if results['add_user']:
			if not results['password']:
				return 'Password required to add a user'
			params = self.get_params('add', results['add_user'])
			params['password'] = results['password']
			if self.options['default_groups']:
				params['groups'] = self.options['default_groups']
		elif results['del_user']:
			params = self.get_params('delete', results['del_user'])
		elif results['enable_user']:
			params = self.get_params('enable', results['enable_user'])
		elif results['disable_user']:
			params = self.get_params('disable', results['disable_user'])
		else:
			return 'Must select either add, delete, enable or disable'
		return self.process_request(params)

	def config_parser(self, config):
		self.options['host'] = config.get('host')
		self.options['port'] = config.getint('port')
		self.options['use_ssl'] = config.getboolean('use_ssl')
		self.options['secret'] = config.get('secret')
		if config.has_option('default_groups'):
			self.options['default_groups'] = config.get('default_groups')
		else:
			self.options['default_groups'] = None
		return self.options
