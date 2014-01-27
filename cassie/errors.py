class CassieError(Exception):
	pass

class CassieXMPPError(Exception):
	pass

class CassieCommandError(Exception):
	def __init__(self, message):
		self.message = message
