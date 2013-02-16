import json
import urllib2
from cassie.argparselite import ArgumentParserLite

def url_shorten(bot, args):
	parser = ArgumentParserLite('url_shorten', 'use a url shortener service')
	parser.add_argument('-u', '--url', dest = 'url', default = None, required = True, help = 'username to add')
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

def init_bot(bot, opts):
	bot.add_command(url_shorten, 'url_shorten')
