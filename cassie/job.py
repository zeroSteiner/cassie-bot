import time
import uuid
import datetime
import threading

class JobRun(threading.Thread):
	def __init__(self, callback, *args):
		self.callback = callback
		self.callback_args = args
		threading.Thread.__init__(self)

	def run(self):
		self.callback(*self.callback_args)

# Job Dictionary Details:
#   last_run: datetime.datetime
#   run_every: datetime.timedelta
#   job: None or JobRun instance
#   callback: function
#   parameters: parameter to be passed to the callback function
#   enabled: boolean if false do not run the job
class JobManager(threading.Thread):
	def __init__(self):
		self.__jobs__ = {}
		self.running = True
		threading.Thread.__init__(self)

	def stop(self):
		self.running = False
		for job_id, job_desc in self.__jobs__.items():
			if job_desc['job'] == None:
				continue
			if not job_desc['job'].is_alive():
				continue
			job_desc['job'].join()
		self.join()
		return

	def run(self):
		while self.running:
			time.sleep(1)
			for job_id, job_desc in self.__jobs__.items():
				if job_desc['last_run'] + job_desc['run_every'] >= datetime.datetime.utcnow():
					continue
				if job_desc['job'] != None and job_desc['job'].is_alive():
					continue
				job_desc['last_run'] = datetime.datetime.utcnow() # still update the timestamp
				if not job_desc['enabled']:
					continue
				job_desc['job'] = JobRun(job_desc['callback'], job_desc['parameters'])
				job_desc['job'].start()

	def job_add(self, callback, parameters, hours = 0, minutes = 10, seconds = 0):
		job_desc = {}
		job_desc['job'] = None
		job_desc['last_run'] = datetime.datetime.utcnow()
		job_desc['run_every'] = datetime.timedelta(0, ((hours * 60 * 60) + (minutes * 60) + seconds))
		job_desc['callback'] = callback
		job_desc['parameters'] = parameters
		job_desc['enabled'] = True
		job_id = uuid.uuid4()
		self.__jobs__[job_id] = job_desc
		return job_id

	def job_count(self):
		return len(self.__jobs__)

	def job_count_enabled(self):
		return len(filter(lambda job_desc: job_desc['enabled'], self.__jobs__.values()))

	def job_enable(self, job_id):
		if isinstance(job_id, str):
			job_id = uuid.UUID(job_id)
		job_desc = self.__jobs__[job_id]
		job_desc['enabled'] = True

	def job_disable(self, job_id):
		if isinstance(job_id, str):
			job_id = uuid.UUID(job_id)
		job_desc = self.__jobs__[job_id]
		job_desc['enabled'] = False

	def job_del(self, job_id):
		if isinstance(job_id, str):
			job_id = uuid.UUID(job_id)
		del self.__jobs__[job_id]
