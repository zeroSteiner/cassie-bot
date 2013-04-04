import json
import urllib2
from cassie.argparselite import ArgumentParserLite
from cassie.templates import CassieXMPPBotModule

class Module(CassieXMPPBotModule):
	def cmd_url_shorten(self, args, jid):
		parser = ArgumentParserLite('url_shorten', 'use a url shortener service')
		parser.add_argument('-u', '--url', dest = 'url', default = None, required = True, help = 'url to shorten')
		if not len(args):
			return parser.format_help()
		results = parser.parse_args(args)
		if not results:
			return parser.get_last_error()

		data = json.dumps({'longUrl':results['url']})
		request = urllib2.Request('https://www.googleapis.com/urlshortener/v1/url', data, {'Content-Type':'application/json'})
		response = json.load(urllib2.urlopen(request))
		short_url = str(response['id'])
		return short_url
