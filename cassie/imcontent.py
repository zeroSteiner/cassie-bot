import markdown
from sleekxmpp.xmlstream import ET

def normalize_text(text):
	if isinstance(text, (list, tuple)):
		text = '\n'.join(text)
	if not isinstance(text, str):
		raise Exception('data can not be reliably converted to a string')
	text = text.strip()
	return text

def markdown_to_html(text):
	return markdown.markdown(text, extensions = ['nl2br'], output_format = 'html4')

def markdown_to_xhtml(text):
	return markdown.markdown(text, extensions = ['nl2br'], output_format = 'xhtml1')

class IMContentText:
	def __init__(self, text, font = None, prepend_newline = False):
		self.text = normalize_text(text)
		if prepend_newline:
			self.text = '\n' + self.text
		self.font = font

	def get_text(self):
		return self.text

	def get_xhtml(self, element = True):
		lines = self.text.split('\n')
		xhtml = ET.Element('span')
		if self.font:
			xhtml.set('style', 'font-family: ' + self.font + ';')
		for subline in lines[:-1]:
			p = ET.SubElement(xhtml, 'p')
			p.text = subline
			ET.SubElement(xhtml, 'br')
		p = ET.SubElement(xhtml, 'p')
		p.text = lines[-1]
		if element:
			return xhtml
		return ET.tostring(xhtml)

class IMContentMarkdown(IMContentText):
	def get_xhtml(self, element = True):
		xhtml = ET.XML(markdown_to_xhtml(self.text))
		if self.font:
			span = ET.Element('span')
			span.set('style', 'font-family: ' + self.font + ';')
			span.append(xhtml)
			xhtml = span
		if element:
			return xhtml
		return ET.tostring(xhtml)
