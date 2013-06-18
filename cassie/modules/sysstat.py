import psutil
from cassie.utils import generate_progress_bar
from cassie.templates import CassieXMPPBotModule

class Module(CassieXMPPBotModule):
	def cmd_sysstat(self, args, jid, is_muc):
		response = []
		mp_lengths = map(lambda x:len(x.mountpoint), psutil.disk_partitions())
		mp_lengths.sort()
		longest_mount_point = mp_lengths.pop()
		disk_format_string = "{0: <" + str(max(longest_mount_point, 8)) + "} {1}"
		response.append('')
		response.append('== Disk Usage ==')
		for device in psutil.disk_partitions():
			usage = psutil.disk_usage(device.mountpoint)
			response.append(disk_format_string.format(device.mountpoint, generate_progress_bar(usage.used, usage.total)))
		response.append('')
		response.append('== Memory Usage ==')
		vmem = psutil.virtual_memory()
		response.append("{0: <8} {1}".format('Virtual', generate_progress_bar(vmem.percent)))
		swap = psutil.swap_memory()
		response.append("{0: <8} {1}".format('Swap', generate_progress_bar(swap.percent)))
		response.append('')
		response.append('== CPU Usage ==')
		cpu_usages = psutil.cpu_percent(interval = 1, percpu = True)
		for cpu in xrange(len(cpu_usages)):
			response.append("{0: <8} {1}".format('CPU-' + str(cpu), generate_progress_bar(cpu_usages[cpu])))
		return '\n'.join(response)
