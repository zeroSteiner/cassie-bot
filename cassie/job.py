import time
import uuid
import datetime
import threading

__version__ = '0.1'
__all__ = ['JobRun', 'JobManager']

def normalize_job_id(job_id):
	if isinstance(job_id, str):
		job_id = uuid.UUID(job_id)
	if not isinstance(job_id, uuid.UUID):
		raise Exception('invalid job id, must be uuid.UUID instance')
	return job_id

class JobRun(threading.Thread):
	def __init__(self, callback, *args):
		self.callback = callback
		self.callback_args = args
		self.exception = None
		self.reaped = False
		threading.Thread.__init__(self)

	def run(self):
		try:
			self.callback(*self.callback_args)
		except Exception as error:
			self.exception = error
		return

# Job Dictionary Details:
#   last_run: datetime.datetime
#   run_every: datetime.timedelta
#   job: None or JobRun instance
#   callback: function
#   parameters: parameter to be passed to the callback function
#   enabled: boolean if false do not run the job
#   tolerate_exceptions: boolean if true this job will run again after a failure
#   expiration: number of times to run a job or -1 for infinite
class JobManager(threading.Thread):
	def __init__(self):
		self.__jobs__ = {}
		self.running = True
		self.job_lock = threading.Lock()
		threading.Thread.__init__(self)

	def stop(self):
		self.running = False
		self.job_lock.acquire()
		for job_id, job_desc in self.__jobs__.items():
			if job_desc['job'] == None:
				continue
			if not job_desc['job'].is_alive():
				continue
			job_desc['job'].join()
		self.join()
		self.job_lock.release()
		return

	def reap(self):
		jobs_for_removal = []
		for job_id, job_desc in self.__jobs__.items():
			if job_desc['job'].is_alive() or job_desc['job'].reaped:
				continue
			if job_desc['job'].exception != None and job_desc['tolerate_exceptions'] == False:
				jobs_for_removal.append(job_id)
			if job_desc['expiration'] > -1:
				if job_desc['expiration'] == 0:
					jobs_for_removal.append(job_id)
				else:
					job_desc['expiration'] -= 1
			job_desc['job'].reaped = True
		for job_id in jobs_for_removal:
			self.job_del(job_id)

	def run(self):
		self.job_lock.acquire()
		while self.running:
			self.job_lock.release()
			time.sleep(1)
			self.job_lock.acquire()
			if not self.running:
				break
			self.reap()
			for job_id, job_desc in self.__jobs__.items():
				if job_desc['last_run'] + job_desc['run_every'] >= datetime.datetime.utcnow():
					continue
				if job_desc['job'].is_alive():
					continue
				if not job_desc['job'].reaped:
					continue
				job_desc['last_run'] = datetime.datetime.utcnow() # still update the timestamp
				if not job_desc['enabled']:
					continue
				job_desc['job'] = JobRun(job_desc['callback'], job_desc['parameters'])
				job_desc['job'].start()
		self.job_lock.release()

	def job_add(self, callback, parameters, hours = 0, minutes = 0, seconds = 0, tolerate_exceptions = True, expiration = -1):
		job_desc = {}
		job_desc['job'] = JobRun(callback, parameters)
		job_desc['last_run'] = datetime.datetime.utcnow()
		job_desc['run_every'] = datetime.timedelta(0, ((hours * 60 * 60) + (minutes * 60) + seconds))
		job_desc['callback'] = callback
		job_desc['parameters'] = parameters
		job_desc['enabled'] = True
		job_desc['tolerate_exceptions'] = tolerate_exceptions
		job_desc['expiration'] = expiration
		job_id = uuid.uuid4()
		with self.job_lock:
			self.__jobs__[job_id] = job_desc
		return job_id

	def job_count(self):
		return len(self.__jobs__)

	def job_count_enabled(self):
		return len(filter(lambda job_desc: job_desc['enabled'], self.__jobs__.values()))

	def job_enable(self, job_id):
		job_id = normalize_job_id(job_id)
		with self.job_lock:
			job_desc = self.__jobs__[job_id]
			job_desc['enabled'] = True

	def job_disable(self, job_id):
		job_id = normalize_job_id(job_id)
		with self.job_lock:
			job_desc = self.__jobs__[job_id]
			job_desc['enabled'] = False

	def job_del(self, job_id):
		job_id = normalize_job_id(job_id)
		with self.job_lock:
			del self.__jobs__[job_id]

	def job_exists(self, job_id):
		job_id = normalize_job_id(job_id)
		if job_id in self.__jobs__:
			return True
		else:
			return False
