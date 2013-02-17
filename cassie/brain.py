import re
import threading
import aiml
from copy import copy
from time import sleep
from httplib import CannotSendRequest

def getError(elem):
	for e in elem:
		if isinstance(e, list) and e[0] == 'error':
			return e

def getFail(elem):
	for e in elem:
		if isinstance(e, list) and e[0] == 'fail':
			return e

def getSuccess(elem):
	for e in elem:
		if isinstance(e, list) and e[0] == 'success':
			return e

class Brain(object, aiml.Kernel):
	def __init__(self, modules, *args, **kwargs):
		self.__threads__ = []
		self.__jobs__ = []
		self.__shutdown__ = False
		
		aiml.Kernel.__init__(self)
		self._elementProcessors['error'] = self._processError
		self._elementProcessors['fail'] = self._processFail
		self._elementProcessors['success'] = self._processSuccess
		aiml.AimlParser.AimlHandler._validationInfo101['error'] = ( [], [], True )
		aiml.AimlParser.AimlHandler._validationInfo101['fail'] = ( [], [], True )
		aiml.AimlParser.AimlHandler._validationInfo101['success'] = ( [], [], True )
		
		self.modules = modules
		for module in modules.values():
			module.init_brain(self)
	
	def __del__(self):
		self.stop()
	
	@classmethod
	def add_element_parser(cls, handler, tag_name, validation_info):
		cls_method = types.MethodType(handler, cls)
		self._elementProcessors[tag_name] = cls_method
		aiml.AimlParser.AimlHandler._validationInfo101[tag_name] = validation_info
		return setattr(cls, handler.__name__, cls_method)
			
	def _processError(self, elem, sessionID):
		newPhrase = ''
		for e in elem[2:]:
			newPhrase += self._processElement(e, sessionID)
		return newPhrase

	def _processFail(self, elem, sessionID):
		newPhrase = ''
		for e in elem[2:]:
			newPhrase += self._processElement(e, sessionID)
		return newPhrase
		
	def _processSuccess(self, elem, sessionID):
		newPhrase = ''
		for e in elem[2:]:
			newPhrase += self._processElement(e, sessionID)
		return newPhrase
