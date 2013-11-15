Cassie Install
==

Required Packages
--
[SleekXMPP](https://github.com/fritzy/SleekXMPP)

[PyAIML](https://github.com/zeroSteiner/pyAIML)

[Python-Markdown](http://pythonhosted.org/Markdown/)

Getting Started
--
1. Install all of the dependencies from the locations described above.
1. Copy the contents of the cassie-bot directory to it's default location of /opt/cassie-bot.
1. Copy the example cassie.conf.txt file to /opt/cassie-bot/cassie.conf and set it's options appropriately.
	1. The xmpp/admin option should be set to an existing user on the XMPP server.  This user will be the first bot administrator.
	1. Ensure that the aiml folders are chowned to the user corresponding to the config files's setuid value with write access. Write access is required for self updates.
	1. Ensure that the user corresponding to the config file's setuid value has access to write the xmpp/users_file file for the user database.
	1. Enable modules by adding them into the config file under their own section prefixed with mod\_.  For example the foo module is enabled by adding a section [mod_foo] to the config file.
1. Copy the appropriate service file to it's corresponding destination.

Modules
--
Modules have additional dependencies beyond those listed in the "Required
Packages" section.  Some modules take options which can be set by adding them
under the modules config file section.

For example to set the 'bar' option for the 'foo' module to 1 would be done as
follows:

	[mod_foo]
	bar: 1
