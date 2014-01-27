import aiml
import types

class Brain(object, aiml.Kernel):
	def __init__(self, modules, *args, **kwargs):
		self.__threads__ = []
		self.__jobs__ = []
		self.__shutdown__ = False
		if modules == None:
			modules = {}
		aiml.Kernel.__init__(self)
		self.modules = modules
		for module in modules.values():
			module.init_brain(self)

	def __del__(self):
		self.stop()

	def add_element_parser(self, handler, tag_name, validation_info):
		cls_method = types.MethodType(handler, self)
		self._elementProcessors[tag_name] = cls_method
		aiml.AimlParser.AimlHandler._validationInfo101[tag_name] = validation_info
		return setattr(self, handler.__name__, cls_method)
